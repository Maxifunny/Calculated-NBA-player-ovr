from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler


def prepare_defensive_and_pie_features(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Fill in optional defensive / PIE columns so downstream models don't need
    to care whether PBP play-by-play was available.
    """
    out = frame.copy()

    if "def_events_per_100" in out.columns and "stocks_per_100" in out.columns:
        out["def_events_per_100"] = out["def_events_per_100"].fillna(out["stocks_per_100"])

    # PIE exists on NBA.com; BBRef-only runs may leave it empty → use VORP-shaped proxy.
    if "pie" in out.columns and "vorp" in out.columns:
        out["pie"] = out["pie"].fillna(out["vorp"])

    return out


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def robust_01(values: pd.Series, *, min_points: int = 5, iqr_squash: float = 1.5) -> np.ndarray:
    """
    Map a feature to roughly [0, 1] with outlier compression using RobustScaler(IQR),
    then squash and min-max using percentile anchors (2%..98%).
    """
    array = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(array)
    out = np.full(array.shape[0], 0.5, dtype=float)
    if finite.sum() < min_points:
        return out

    scaler = RobustScaler()
    transformed = scaler.fit_transform(array[finite].reshape(-1, 1)).ravel()
    squashed = _sigmoid(transformed / float(iqr_squash))

    low, high = np.nanpercentile(squashed, 2), np.nanpercentile(squashed, 98)
    if high - low < 1e-9:
        out[finite] = 0.5
        return out

    unit = np.clip((squashed - low) / (high - low), 0, 1)
    out[finite] = unit
    return out


def robust_01_grouped(
    values: pd.Series,
    groups: pd.Series,
    *,
    min_points_per_group: int = 5,
    default: float = 0.5,
) -> np.ndarray:
    """
    Like robust_01, but fit the RobustScaler within each group separately.

    This helps reduce "position placement" artifacts (e.g. PER for centers)
    when the distribution differs strongly by role.
    """
    values_arr = pd.to_numeric(values, errors="coerce")
    group_arr = groups.astype("string").fillna("unknown")

    out = np.full(len(values_arr), default, dtype=float)
    for g in group_arr.unique():
        mask = group_arr == g
        if int(mask.sum()) < min_points_per_group:
            continue
        subset = values_arr[mask]
        out[mask.to_numpy()] = robust_01(subset, min_points=min_points_per_group)
    return out


def position_group(position: pd.Series) -> pd.Series:
    """
    Coarse grouping to reduce "role mismatch" artifacts.

    - center_pf: C or PF
    - wings: SF or SG
    - backcourt: PG

    Any other/unknown position is mapped to "other".
    """
    pos = position.astype("string").fillna("unknown").str.upper()
    out = pd.Series("other", index=pos.index, dtype="string")
    out[pos.isin(["C", "PF"])] = "center_pf"
    out[pos.isin(["SF", "SG"])] = "wings"
    out[pos.isin(["PG"])] = "backcourt"
    # Some datasets sometimes contain combined positions like "C-F" or "PF-C".
    out[pos.str.contains("C", na=False) | pos.str.contains("PF", na=False)] = "center_pf"
    out[pos.str.contains("SF", na=False) | pos.str.contains("SG", na=False)] = "wings"
    out[pos.str.contains("PG", na=False)] = "backcourt"
    return out


def rank_percentiles(raw: np.ndarray) -> np.ndarray:
    """
    Convert raw scores to global percentiles in a deterministic way.
    Output is non-decreasing with raw values (ties use average rank).
    """
    # pd.Series.rank(pct=True) is stable/deterministic given the input ordering.
    return pd.Series(raw).rank(method="average", pct=True).to_numpy(dtype=float)


def scale_raw_to_ovr_band(
    raw: np.ndarray | pd.Series,
    *,
    ovr_min: int = 62,
    ovr_max: int = 99,
    anchors_p: Iterable[float] = (0.00, 0.10, 0.35, 0.60, 0.85, 0.95, 0.99, 1.00),
):
    """
    Monotonic, stable percentile→overall mapping to the NBA2K-like band.

    - Percentiles are computed globally (caller can do grouping externally).
    - Piecewise anchors mimic the empirical rotation distribution:
        most players ~68..82, stars ~90+.
    """
    raw_arr = pd.to_numeric(raw, errors="coerce").to_numpy(dtype=float)
    order = rank_percentiles(raw_arr)

    anchors_o = np.array([ovr_min, 68, 73, 78, 85, 91, 96, ovr_max], dtype=float)
    overall = np.interp(order, np.array(list(anchors_p), dtype=float), anchors_o)
    return np.rint(overall).astype(int)


def minutes_credibility_percentile(
    frame: pd.DataFrame,
    *,
    position_group_series: pd.Series,
    floor_by_group: dict[str, float] | None = None,
    gamma: float = 1.2,
) -> np.ndarray:
    """
    Compute a "minutes credibility" factor in [0.35..1.0].

    The main design goal:
      - shrink PER-driven volatility on reserves / small samples
      - but do not over-penalize centers (role variance is different).

    Implementation:
      - compute total minutes = gp * mpg
      - convert to within-position percentiles
      - credibility = floor + (1-floor)*pct^gamma
    """
    floor_by_group = floor_by_group or {
        "center_pf": 0.45,
        "wings": 0.40,
        "backcourt": 0.40,
        "other": 0.40,
    }

    gp = pd.to_numeric(frame.get("gp"), errors="coerce").fillna(0.0).to_numpy(dtype=float)
    mpg = pd.to_numeric(frame.get("mpg"), errors="coerce").fillna(0.0).to_numpy(dtype=float)
    total_minutes = gp * mpg

    out = np.full(len(frame), 0.40, dtype=float)
    grp = position_group_series.astype("string").fillna("other")
    for g in grp.unique():
        mask = grp == g
        if int(mask.sum()) == 0:
            continue
        pct = pd.Series(total_minutes[mask]).rank(method="average", pct=True).to_numpy(dtype=float)
        floor = float(floor_by_group.get(str(g), 0.40))
        out[mask.to_numpy()] = floor + (1.0 - floor) * np.power(np.clip(pct, 0, 1), float(gamma))
    return np.clip(out, 0.35, 1.0)


def ensure_required_columns(frame: pd.DataFrame, required: list[str]) -> None:
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

