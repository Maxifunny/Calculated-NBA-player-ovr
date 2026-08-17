"""Stage 1 — Play-by-play from stats.nba.com (run this on a home network)."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd

from nba_ovr.settings import PBP_MAX_GAMES, PBP_SLEEP_SECONDS, RAW_DIR, SEASON

logger = logging.getLogger(__name__)


def _pbp_dir() -> Path:
    path = RAW_DIR / "pbp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def unique_game_ids(game_log: pd.DataFrame) -> list[str]:
    if game_log.empty or "GAME_ID" not in game_log.columns:
        return []
    ids = game_log["GAME_ID"].astype(str).drop_duplicates().tolist()
    ids.sort()
    if PBP_MAX_GAMES > 0:
        ids = ids[:PBP_MAX_GAMES]
    return ids


def fetch_play_by_play(game_id: str) -> pd.DataFrame:
    from nba_api.stats.endpoints import playbyplayv2
    from nba_api.stats.library.http import NBAStatsHTTP
    from nba_ovr.settings import NBA_API_TIMEOUT

    NBAStatsHTTP.TIMEOUT = NBA_API_TIMEOUT
    data = playbyplayv2.PlayByPlayV2(game_id=game_id, timeout=NBA_API_TIMEOUT)
    frame = data.get_data_frames()[0]
    frame["GAME_ID"] = game_id
    return frame


def extract_play_by_play(game_log: pd.DataFrame) -> Path:
    """Download PBP JSON per game with checkpoints so a rate-limit does not wipe progress."""
    out_dir = _pbp_dir()
    game_ids = unique_game_ids(game_log)
    logger.info("Play-by-play target: %s games (PBP_MAX_GAMES=%s)", len(game_ids), PBP_MAX_GAMES)

    failures = 0
    for index, game_id in enumerate(game_ids, start=1):
        dest = out_dir / f"{game_id}.json"
        if dest.exists():
            continue
        try:
            frame = fetch_play_by_play(game_id)
            dest.write_text(frame.to_json(orient="records"), encoding="utf-8")
            if index % 10 == 0:
                logger.info("PBP %s/%s saved (%s events)", index, len(game_ids), len(frame))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            logger.warning("PBP failed for game %s: %s", game_id, exc)
            if failures >= 8:
                logger.error("Too many PBP failures — stopping early. Re-run later to resume.")
                break
        time.sleep(PBP_SLEEP_SECONDS)

    manifest = {
        "season": SEASON,
        "requested_games": len(game_ids),
        "saved_files": len(list(out_dir.glob("*.json"))),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out_dir
