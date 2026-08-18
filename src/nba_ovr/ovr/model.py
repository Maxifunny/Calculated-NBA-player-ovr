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


def run_ovr() -> pd.DataFrame:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    mart = read_mart()
    if mart.empty:
        raise RuntimeError("player_ovr_mart is empty — run stages 1-3 first.")
    result = compute_true_ovr(mart)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = PROCESSED_DIR / "true_ovr.csv"
    result.to_csv(out_csv, index=False)
    summary = {
        "players": int(len(result)),
        "true_ovr_min": int(result["true_ovr"].min()),
        "true_ovr_max": int(result["true_ovr"].max()),
        "true_ovr_mean": float(result["true_ovr"].mean()),
        "matched_2k": int(result["ovr_2k"].notna().sum()),
        "weights": OVR_WEIGHTS,
    }
    (REPORTS_DIR / "ovr_model_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Stage 4 complete: %s", summary)
    preview_cols = [c for c in ["player_name", "pts", "per", "ovr_2k", "true_ovr", "ovr_gap"] if c in result.columns]
    logger.info("\n%s", result.sort_values("true_ovr", ascending=False)[preview_cols].head(10).to_string(index=False))
    return result


if __name__ == "__main__":
    run_ovr()
