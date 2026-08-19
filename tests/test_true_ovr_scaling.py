import numpy as np

from nba_ovr.ovr.model import scale_to_2k_range
from nba_ovr.settings import OVR_SCALE_MAX, OVR_SCALE_MIN


def test_scale_to_2k_range_bounded_62_99_and_monotonic():
    raw = np.linspace(0.0, 1.0, 201)
    scaled = scale_to_2k_range(raw)
    assert scaled.min() >= OVR_SCALE_MIN
    assert scaled.max() <= OVR_SCALE_MAX
    assert np.all(np.diff(scaled) >= 0), "scaled values must be non-decreasing w.r.t raw order"


def test_scale_to_2k_range_non_decreasing_with_ties():
    # Include repeated raw values (ties → same/adjacent ranks).
    raw = np.array([0.0, 0.05, 0.05, 0.2, 0.6, 0.6, 1.0], dtype=float)
    scaled = scale_to_2k_range(raw)
    assert np.all(np.diff(scaled) >= 0), "ties should not break monotonicity"

