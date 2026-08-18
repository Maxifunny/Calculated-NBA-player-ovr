"""Stage 3 — load processed Spark output into PostgreSQL (or SQLite)."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from nba_ovr.settings import DATABASE_URL, GAME_VERSION, PROCESSED_DIR, ROOT, SEASON

logger = logging.getLogger(__name__)

SCHEMA_PATH = ROOT / "src" / "nba_ovr" / "warehouse" / "schema.sql"
VIEWS_PATH = ROOT / "src" / "nba_ovr" / "warehouse" / "views.sql"


def _engine():
    return create_engine(DATABASE_URL, future=True)


def _run_sql_file(engine, path: Path) -> None:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        lines.append(line)
    body = "\n".join(lines)
    chunks = [chunk.strip() for chunk in body.split(";") if chunk.strip()]
    with engine.begin() as conn:
        for chunk in chunks:
            conn.execute(text(chunk))


def _processed_frame() -> pd.DataFrame:
    flat = PROCESSED_DIR / "players_clean.csv"
    if flat.exists() and flat.is_file():
        return pd.read_csv(flat)
    parquet = PROCESSED_DIR / "players_clean.parquet"
    if parquet.exists():
        return pd.read_parquet(parquet)
    raise FileNotFoundError("Brak processed_data/players_clean.csv — uruchom Etap 2 (Spark ETL).")


def load_warehouse() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    engine = _engine()
    logger.info("Warehouse URL: %s", DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL)

    _run_sql_file(engine, SCHEMA_PATH)

    frame = _processed_frame()
    logger.info("Loading %s processed rows", len(frame))

    players = pd.DataFrame(
        {
            "player_id": frame["player_id"].astype(int),
            "bbref_id": frame["bbref_id"] if "bbref_id" in frame.columns else None,
            "player_name": frame["player_name"],
            "name_key": frame["name_key"],
            "team_abbreviation": frame.get("team_abbreviation"),
            "position": frame.get("position"),
            "age": pd.to_numeric(frame["age"], errors="coerce").astype("Int64") if "age" in frame.columns else None,
            "season": frame.get("season", SEASON),
        }
    ).drop_duplicates("player_id")

    stats_cols = [
        "gp",
        "mpg",
        "pts",
        "ast",
        "reb",
        "per",
        "ts_pct",
        "usg_pct",
        "bpm",
        "obpm",
        "dbpm",
        "vorp",
        "dws",
        "ast_pct",
        "pie",
        "stocks_per_100",
        "usage_efficiency",
        "def_events_per_100",
        "per_percentile",
    ]
    advanced = pd.DataFrame({"player_id": frame["player_id"].astype(int), "season": frame.get("season", SEASON)})
    for column in stats_cols:
        advanced[column] = pd.to_numeric(frame[column], errors="coerce") if column in frame.columns else None

    ratings = pd.DataFrame(
        {
            "player_id": frame["player_id"].astype(int),
            "player_name": frame["player_name"],
            "overall": pd.to_numeric(frame["ovr_2k"], errors="coerce").astype("Int64")
            if "ovr_2k" in frame.columns
            else None,
            "position": frame.get("position_2k"),
            "team": frame.get("team_2k"),
            "slug": frame.get("slug_2k"),
            "game_version": GAME_VERSION,
            "name_match_score": frame.get("name_match_score"),
            "season": frame.get("season", SEASON),
        }
    )
    ratings = ratings[ratings["overall"].notna()].drop_duplicates(["player_id", "season", "game_version"])

    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text("DELETE FROM nba_2k_ratings"))
        conn.execute(text("DELETE FROM advanced_stats"))
        conn.execute(text("DELETE FROM players"))

    players.to_sql("players", engine, if_exists="append", index=False)
    advanced.to_sql("advanced_stats", engine, if_exists="append", index=False)
    ratings.to_sql("nba_2k_ratings", engine, if_exists="append", index=False)

    _run_sql_file(engine, VIEWS_PATH)

    with engine.connect() as conn:
        mart_count = conn.execute(text("SELECT COUNT(*) FROM player_ovr_mart")).scalar()
    logger.info("Stage 3 complete. player_ovr_mart rows=%s", mart_count)


def read_mart() -> pd.DataFrame:
    engine = _engine()
    return pd.read_sql("SELECT * FROM player_ovr_mart", engine)


if __name__ == "__main__":
    load_warehouse()
