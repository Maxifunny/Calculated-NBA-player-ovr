"""Stage 1 — Official-ish NBA 2K overalls from the public nba2kapi (scrapes 2kratings.com)."""

from __future__ import annotations

import logging
import time

import pandas as pd

from nba_ovr.ingest.http_utils import request_with_retry
from nba_ovr.settings import GAME_VERSION

logger = logging.getLogger(__name__)

PUBLIC_PLAYERS_URL = "https://api.nba2kapi.com/api/public/players"


def fetch_2k_ratings(team_type: str = "curr", page_size: int = 100) -> pd.DataFrame:
    """Paginate the public 2K ratings API. No API key required (IP rate-limited)."""
    rows: list[dict] = []
    cursor: str | None = None
    while True:
        params = {"teamType": team_type, "limit": page_size}
        if cursor:
            params["cursor"] = cursor
        response = request_with_retry(PUBLIC_PLAYERS_URL, params=params, timeout=45)
        payload = response.json()
        if not payload.get("success"):
            raise RuntimeError(f"2K API error: {payload}")
        batch = payload.get("data") or []
        rows.extend(batch)
        meta = (payload.get("meta") or {}).get("pagination") or {}
        logger.info("2K ratings page: +%s (total downloaded %s / %s)", len(batch), len(rows), meta.get("total"))
        if not meta.get("hasMore"):
            break
        cursor = meta.get("nextCursor")
        if not cursor:
            break
        time.sleep(0.4)

    if not rows:
        raise RuntimeError("2K API returned no current players")

    records = []
    for player in rows:
        positions = player.get("positions") or []
        records.append(
            {
                "player_name": player.get("name"),
                "overall": player.get("overall"),
                "team": player.get("team"),
                "position": positions[0] if positions else None,
                "positions": "|".join(positions),
                "archetype": player.get("archetype"),
                "slug": player.get("slug"),
                "game_version": GAME_VERSION,
                "team_type": player.get("teamType") or team_type,
                "height": player.get("height"),
                "weight": player.get("weight"),
                "last_updated": player.get("lastUpdated"),
            }
        )
    frame = pd.DataFrame.from_records(records)
    frame = frame.drop_duplicates(subset=["slug", "team_type"], keep="first")
    logger.info("2K ratings: %s unique current players", len(frame))
    return frame
