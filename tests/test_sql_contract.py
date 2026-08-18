from pathlib import Path

from nba_ovr.warehouse.load import SCHEMA_PATH, VIEWS_PATH


def test_schema_defines_the_three_core_tables():
    sql = SCHEMA_PATH.read_text(encoding="utf-8").lower()
    for table in ("create table if not exists players", "advanced_stats", "nba_2k_ratings"):
        assert table in sql


def test_view_joins_all_three_tables():
    sql = VIEWS_PATH.read_text(encoding="utf-8").lower()
    assert "create view player_ovr_mart" in sql
    assert "join advanced_stats" in sql
    assert "left join nba_2k_ratings" in sql
    assert Path(SCHEMA_PATH).exists()
