"""Stage 4 — heuristic True OVR.

We deliberately do NOT train a model on 2K overalls. That would copy 2K's
scoring bias (points, popularity, recency) which is exactly what this project
is trying to challenge. Weights are explicit so you can argue with them.
"""

from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler

from nba_ovr.settings import OVR_SCALE_MAX, OVR_SCALE_MIN, OVR_WEIGHTS, PROCESSED_DIR, REPORTS_DIR
from nba_ovr.warehouse.load import read_mart
from nba_ovr.ovr.models.registry import resolve_model_selection
from nba_ovr.ovr.models.utils import position_group

logger = logging.getLogger(__name__)

FEATURE_COLUMNS = list(OVR_WEIGHTS.keys())


def _weighted_sum_ok() -> None:
    total = sum(OVR_WEIGHTS.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"OVR_WEIGHTS must sum to 1.0, got {total}")


def _prepare_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in FEATURE_COLUMNS:
        if column not in out.columns:
            out[column] = np.nan
        out[column] = pd.to_numeric(out[column], errors="coerce")

    # Missing PBP defensive events: fall back to stocks (STL+BLK per 100).
    out["def_events_per_100"] = out["def_events_per_100"].fillna(out["stocks_per_100"])
    # PIE exists on NBA.com; BBRef-only runs leave it empty → use VORP-shaped proxy.
    out["pie"] = out["pie"].fillna(out["vorp"])
    return out


def _robust_01(values: pd.Series) -> np.ndarray:
    """Map a feature to ~[0, 1] with outlier compression (RobustScaler uses IQR)."""
    array = values.to_numpy(dtype=float).reshape(-1, 1)
    finite = np.isfinite(array.ravel())
    scaled = np.full(array.shape[0], 0.5, dtype=float)
    if finite.sum() < 5:
        return scaled
    scaler = RobustScaler()
    transformed = scaler.fit_transform(array[finite]).ravel()
    # squash to 0-1 via a logistic on robust z, then min-max the result
    squashed = 1.0 / (1.0 + np.exp(-transformed / 1.5))
    low, high = np.nanpercentile(squashed, 2), np.nanpercentile(squashed, 98)
    if high - low < 1e-9:
        scaled[finite] = 0.5
        return scaled
    unit = np.clip((squashed - low) / (high - low), 0, 1)
    scaled[finite] = unit
    return scaled


def composite_score(frame: pd.DataFrame) -> pd.DataFrame:
    _weighted_sum_ok()
    prepared = _prepare_features(frame)
    score = np.zeros(len(prepared), dtype=float)
    contributions = {}
    for column, weight in OVR_WEIGHTS.items():
        unit = _robust_01(prepared[column])
        contributions[f"w_{column}"] = unit * weight
        score += unit * weight
    prepared["true_ovr_raw"] = score
    for column, values in contributions.items():
        prepared[column] = values
    return prepared


def scale_to_2k_range(raw: np.ndarray) -> np.ndarray:
    """Percentile curve that mimics 2K: most rotation players 68-82, stars 90+."""
    order = pd.Series(raw).rank(method="average", pct=True).to_numpy()
    # Piecewise mapping from percentile → overall.
    anchors_p = np.array([0.00, 0.10, 0.35, 0.60, 0.85, 0.95, 0.99, 1.00])
    anchors_o = np.array(
        [
            OVR_SCALE_MIN,
            68,
            73,
            78,
            85,
            91,
            96,
            OVR_SCALE_MAX,
        ]
    )
    overall = np.interp(order, anchors_p, anchors_o)
    return np.rint(overall).astype(int)


def _minutes_credibility(frame: pd.DataFrame) -> pd.Series:
    """Shrink tiny-minute PER spikes toward league average.

    Backup centers often lead the league in PER/stocks per 100. 2K (and
    humans) still rate them as role players because they do not run an offense.
    Credibility 1.0 ≈ a full-time starter (~36 MPG * 70 GP).
    """
    gp = pd.to_numeric(frame["gp"], errors="coerce").fillna(0) if "gp" in frame.columns else pd.Series(0.0, index=frame.index)
    mpg = pd.to_numeric(frame["mpg"], errors="coerce").fillna(0) if "mpg" in frame.columns else pd.Series(0.0, index=frame.index)
    minutes = gp * mpg
    prior = 500.0  # ~18 mpg * 28 games of average evidence
    return (minutes / (minutes + prior)).clip(lower=0.40, upper=1.0)


def compute_true_ovr(frame: pd.DataFrame) -> pd.DataFrame:
    scored = composite_score(frame)
    cred = _minutes_credibility(scored)
    scored["minutes_credibility"] = cred
    scored["true_ovr_raw"] = 0.5 + (scored["true_ovr_raw"] - 0.5) * cred
    scored["true_ovr"] = scale_to_2k_range(scored["true_ovr_raw"].to_numpy())
    scored["ovr_gap"] = scored["ovr_2k"] - scored["true_ovr"]
    scored["overrated_flag"] = scored["ovr_gap"] >= 5
    scored["underrated_flag"] = scored["ovr_gap"] <= -5
    return scored


def _top_by_gap(frame: pd.DataFrame, *, n: int, ascending: bool) -> pd.DataFrame:
    cols = [c for c in ["player_name", "team_abbreviation", "position", "gp", "pts", "per", "ovr_2k", "true_ovr", "ovr_gap"] if c in frame.columns]
    return frame.sort_values("ovr_gap", ascending=ascending).head(n)[cols].copy()


def _center_pf_underrated_dominance(result: pd.DataFrame, top_underrated: pd.DataFrame, *, q75: float = 0.75) -> dict:
    if result.empty or "true_ovr" not in result.columns or "position" not in result.columns:
        return {}
    q = float(np.nanquantile(result["true_ovr"], q75)) if result["true_ovr"].notna().any() else np.nan
    pos_grp = position_group(result["position"])
    res2 = result[["player_name", "true_ovr"]].copy()
    res2["pos_grp"] = pos_grp.values
    merged = top_underrated.merge(res2, on="player_name", how="left", suffixes=("", "_r"))
    center_mask = merged["pos_grp"] == "center_pf"
    high_center_mask = center_mask & (merged["true_ovr"] >= q)
    total = max(len(merged), 1)
    return {
        "q75_true_ovr": q,
        "center_pf_count": int(center_mask.sum()),
        "high_center_pf_count": int(high_center_mask.sum()),
        "center_pf_share": center_mask.sum() / total,
        "high_center_pf_share": high_center_mask.sum() / total,
    }


def _write_model_top_csvs(*, result: pd.DataFrame, model_name: str, top_n: int) -> None:
    top_over = _top_by_gap(result, n=top_n, ascending=False)
    top_under = _top_by_gap(result, n=top_n, ascending=True)
    top_over.to_csv(REPORTS_DIR / f"model_{model_name}_top_overrated.csv", index=False)
    top_under.to_csv(REPORTS_DIR / f"model_{model_name}_top_underrated.csv", index=False)


def _write_model_comparison_md(*, by_model: dict[str, pd.DataFrame], top_n: int) -> None:
    lines: list[str] = []
    lines.append("# True OVR model comparison\n\n")
    lines.append(f"Artifacts: `reports/model_<name>_top_overrated.csv`, `reports/model_<name>_top_underrated.csv`.\n\n")

    for model_name, result in sorted(by_model.items()):
        if result.empty:
            lines.append(f"## {model_name}\n- no data\n\n")
            continue
        mn, mx = int(result["true_ovr"].min()), int(result["true_ovr"].max())
        lines.append(f"## {model_name}\n- true_ovr range: {mn}..{mx}\n")
        top_under = _top_by_gap(result, n=top_n, ascending=True)
        metrics = _center_pf_underrated_dominance(result, top_under)
        if metrics:
            lines.append(
                f"- center_pf share among top underrated: {metrics['center_pf_share']:.0%} "
                f"({metrics['center_pf_count']}/{top_n})\n"
            )
            lines.append(
                f"- high center_pf share (true_ovr ≥ p75={metrics['q75_true_ovr']:.1f}): "
                f"{metrics['high_center_pf_share']:.0%} "
                f"({metrics['high_center_pf_count']}/{top_n})\n"
            )

        if model_name == "v1":
            lines.append("- Why it persists: v1 shrinks the whole composite by minutes credibility; centers can still rank high via defense/efficiency.\n\n")
        elif model_name == "v2":
            lines.append("- Why it persists: v2 normalizes PER within coarse roles and shrinks only PER, reducing volatility without removing center advantage.\n\n")
        elif model_name == "v3":
            lines.append("- Why it persists: v3 blends offense/defense with a center-leaning defense weight, keeping two-way bigs visible.\n\n")

    (REPORTS_DIR / "model_comparison.md").write_text("".join(lines), encoding="utf-8")


def run_ovr(*, model: str = "v1", top_n: int = 10) -> pd.DataFrame:
    """
    Stage 4 orchestrator.

    CLI:
      python -m nba_ovr ovr --model v1|v2|v3|all
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    mart = read_mart()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    if mart.empty:
        logger.warning("player_ovr_mart is empty — generated empty comparison artifacts.")
        (REPORTS_DIR / "model_comparison.md").write_text(
            "# True OVR model comparison\n\nNo data found in `player_ovr_mart` — run stages 1-3 first.\n",
            encoding="utf-8",
        )
        for name in ("v1", "v2", "v3"):
            pd.DataFrame().to_csv(REPORTS_DIR / f"model_{name}_top_overrated.csv", index=False)
            pd.DataFrame().to_csv(REPORTS_DIR / f"model_{name}_top_underrated.csv", index=False)
        return pd.DataFrame()

    selected_models = resolve_model_selection(model)
    by_model: dict[str, pd.DataFrame] = {}

    for m in selected_models:
        model_name = getattr(m, "model_name", model)
        logger.info("Running True OVR %s", model_name)
        result = compute_true_ovr(mart) if model_name == "v1" else m.predict(mart)
        by_model[model_name] = result

        # Persist per-model CSV (and overwrite the legacy one only for single-model runs).
        result.to_csv(PROCESSED_DIR / f"true_ovr_{model_name}.csv", index=False)
        if model != "all" and model_name == model:
            result.to_csv(PROCESSED_DIR / "true_ovr.csv", index=False)

        _write_model_top_csvs(result=result, model_name=model_name, top_n=top_n)

        # Keep compatibility file for Stage 5.
        summary = {
            "model_name": model_name,
            "players": int(len(result)),
            "true_ovr_min": int(result["true_ovr"].min()),
            "true_ovr_max": int(result["true_ovr"].max()),
            "true_ovr_mean": float(result["true_ovr"].mean()),
            "matched_2k": int(result["ovr_2k"].notna().sum()) if "ovr_2k" in result.columns else 0,
            "weights": OVR_WEIGHTS,
        }
        (REPORTS_DIR / "ovr_model_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    _write_model_comparison_md(by_model=by_model, top_n=top_n)

    if model == "all":
        # Stage 5 still expects the legacy `processed_data/true_ovr.csv`.
        if "v1" in by_model:
            by_model["v1"].to_csv(PROCESSED_DIR / "true_ovr.csv", index=False)
        return pd.concat(list(by_model.values()), ignore_index=True)
    return by_model[selected_models[0].model_name]


if __name__ == "__main__":
    run_ovr()
