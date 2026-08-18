import numpy as np
import pandas as pd

from nba_ovr.ovr.model import compute_true_ovr, scale_to_2k_range
from nba_ovr.settings import OVR_SCALE_MAX, OVR_SCALE_MIN, OVR_WEIGHTS


def test_weights_sum_to_one():
    assert abs(sum(OVR_WEIGHTS.values()) - 1.0) < 1e-9


def test_scale_stays_in_2k_like_band():
    raw = np.linspace(0, 1, 200)
    scaled = scale_to_2k_range(raw)
    assert scaled.min() >= OVR_SCALE_MIN
    assert scaled.max() <= OVR_SCALE_MAX
    assert scaled[-1] >= scaled[0]


def test_mvp_like_row_outranks_replacement():
    names = ["Star", "Good", "Average", "Fringe", "Replacement", "Cup"]
    rows = pd.DataFrame(
        {
            "player_name": names,
            "ovr_2k": [97, 88, 78, 74, 70, 66],
            "per": [32.0, 22.0, 16.0, 13.0, 9.0, 6.0],
            "ts_pct": [0.66, 0.60, 0.57, 0.54, 0.51, 0.48],
            "bpm": [11.0, 4.0, 0.5, -1.0, -3.0, -5.0],
            "usage_efficiency": [21.8, 15.0, 12.0, 10.0, 7.1, 5.0],
            "ast_pct": [40.0, 25.0, 15.0, 10.0, 8.0, 5.0],
            "dbpm": [3.0, 1.5, 0.2, -0.4, -1.5, -2.0],
            "stocks_per_100": [3.5, 2.4, 1.8, 1.4, 1.0, 0.6],
            "dws": [4.0, 2.5, 1.5, 0.9, 0.4, 0.1],
            "def_events_per_100": [12.0, 9.0, 7.0, 5.5, 4.0, 2.0],
            "vorp": [8.0, 3.5, 1.2, 0.2, -0.5, -1.2],
                "pie": [20.0, 14.0, 10.0, 7.0, 5.0, 3.0],
                "gp": [70, 70, 70, 60, 50, 20],
                "mpg": [35.0, 32.0, 28.0, 22.0, 16.0, 11.0],
        }
    )
    scored = compute_true_ovr(rows)
    star = scored.loc[scored["player_name"] == "Star", "true_ovr"].iloc[0]
    bench = scored.loc[scored["player_name"] == "Replacement", "true_ovr"].iloc[0]
    assert star > bench
    assert 40 <= star <= 99
    assert 40 <= bench <= 99
