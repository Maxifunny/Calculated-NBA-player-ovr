import pandas as pd

from nba_ovr.settings import MIN_GAMES, MIN_MINUTES_PER_GAME


def apply_rotation_filter(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[(frame["g"] >= MIN_GAMES) & (frame["mp"] >= MIN_MINUTES_PER_GAME)]


def test_rotation_filter_drops_ten_day_contracts():
    frame = pd.DataFrame(
        {
            "player_name": ["Starter", "Cup of coffee"],
            "g": [72, 8],
            "mp": [34.1, 18.0],
        }
    )
    kept = apply_rotation_filter(frame)
    assert list(kept["player_name"]) == ["Starter"]


def test_rotation_filter_drops_low_minute_specialists():
    frame = pd.DataFrame(
        {
            "player_name": ["Rotation", "Garbage time"],
            "g": [60, 50],
            "mp": [22.0, 4.5],
        }
    )
    kept = apply_rotation_filter(frame)
    assert list(kept["player_name"]) == ["Rotation"]
