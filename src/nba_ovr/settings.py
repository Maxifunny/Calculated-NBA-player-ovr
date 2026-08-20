"""Central configuration for the True OVR pipeline.

Change season / filters here rather than scattering magic numbers in scripts.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]

# 2025-26 is the last completed regular season as of August 2026.
# Pair it with NBA 2K26 current-roster ratings (the live 2K card for that year).
SEASON = os.getenv("NBA_SEASON", "2025-26")
SEASON_END_YEAR = int(SEASON.split("-")[0]) + 1
SEASON_TYPE = "Regular Season"
GAME_VERSION = os.getenv("NBA_2K_VERSION", "2K26")

MIN_GAMES = int(os.getenv("MIN_GAMES", "15"))
MIN_MINUTES_PER_GAME = float(os.getenv("MIN_MPG", "10"))

# Play-by-play from stats.nba.com is large and rate-limited. 0 = all games.
PBP_MAX_GAMES = int(os.getenv("PBP_MAX_GAMES", "80"))
PBP_SLEEP_SECONDS = float(os.getenv("PBP_SLEEP_SECONDS", "0.7"))
NBA_API_TIMEOUT = int(os.getenv("NBA_API_TIMEOUT", "60"))
PBP_PROVIDER = os.getenv("PBP_PROVIDER", "nba_api").strip().lower()
PBP_MAX_FAILURES = int(os.getenv("PBP_MAX_FAILURES", "8"))
PBP_RETRY_ATTEMPTS = int(os.getenv("PBP_RETRY_ATTEMPTS", "2"))

RAW_DIR = ROOT / "raw_data"
PROCESSED_DIR = ROOT / "processed_data"
REPORTS_DIR = ROOT / "reports"
WAREHOUSE_DIR = ROOT / "warehouse"

for _path in (RAW_DIR, PROCESSED_DIR, REPORTS_DIR, WAREHOUSE_DIR):
    _path.mkdir(parents=True, exist_ok=True)

# SQLite works without Docker. Point DATABASE_URL at Postgres when you have it.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{WAREHOUSE_DIR / 'nba_ovr.sqlite'}",
)

HTTP_USER_AGENT = (
    "Mozilla/5.0 (compatible; Calculated-NBA-player-ovr/0.1; "
    "+https://github.com/Maxifunny/Calculated-NBA-player-ovr)"
)

# Heuristic True OVR weights. They must sum to 1.0 — tests enforce this.
# Tune these after you look at the first scatter plots; that is the point of v1.
OVR_WEIGHTS = {
    "per": 0.18,
    "ts_pct": 0.12,
    "bpm": 0.10,
    "usage_efficiency": 0.08,
    "ast_pct": 0.07,
    "dbpm": 0.08,
    "stocks_per_100": 0.07,
    "dws": 0.08,
    "def_events_per_100": 0.07,
    "vorp": 0.08,
    "pie": 0.07,
}

OVR_SCALE_MIN = 62
OVR_SCALE_MAX = 99
