"""Stage 1 orchestrator — write raw CSV/JSON into /raw_data."""

from __future__ import annotations

import json
import logging
import zlib
from datetime import UTC, datetime

import pandas as pd

from nba_ovr.ingest.extract_2k import fetch_2k_ratings
from nba_ovr.ingest.extract_bbref import fetch_bbref_season
from nba_ovr.ingest.extract_nba import try_fetch_nba_official
from nba_ovr.ingest.extract_pbp import extract_play_by_play
from nba_ovr.ingest.http_utils import write_csv
from nba_ovr.names import normalize_name
from nba_ovr.settings import RAW_DIR, SEASON

logger = logging.getLogger(__name__)


def _stable_player_id(bbref_id: str | None, fallback_name: str) -> int:
    seed = (bbref_id or fallback_name or "unknown").encode("utf-8")
    return zlib.crc32(seed) & 0x7FFFFFFF


def _rename_bbref(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Prefix overlapping stat columns so the three BBRef tables can be joined."""
    keep = {"bbref_id", "Player", "Tm", "Team", "Pos", "Age", "G", "GS", "MP"}
    renamed = {}
    for column in frame.columns:
        if column in keep or column == "stat_type":
            continue
        renamed[column] = f"{prefix}_{column}"
    return frame.rename(columns=renamed)


def build_player_index(bbref: dict[str, pd.DataFrame], nba: dict[str, pd.DataFrame]) -> pd.DataFrame:
    per_game = _rename_bbref(bbref["bbref_per_game"], "pg")
    advanced = _rename_bbref(bbref["bbref_advanced"], "adv")
    per_poss = _rename_bbref(bbref["bbref_per_poss"], "poss")

    merged = per_game.merge(advanced, on="bbref_id", how="outer", suffixes=("", "_advdup"))
    merged = merged.merge(per_poss, on="bbref_id", how="outer", suffixes=("", "_possdup"))

    if "Player" not in merged.columns:
        for candidate in ("Player_advdup", "Player_possdup"):
            if candidate in merged.columns:
                merged["Player"] = merged[candidate]
                break

    nba_traditional = nba.get("nba_traditional")
    if nba_traditional is not None and "PLAYER_NAME" in nba_traditional.columns:
        nba_traditional = nba_traditional.copy()
        nba_traditional["name_key"] = nba_traditional["PLAYER_NAME"].map(normalize_name)
        merged["name_key"] = merged["Player"].map(normalize_name)
        merged = merged.merge(
            nba_traditional[
                [
                    "name_key",
                    "PLAYER_ID",
                    "TEAM_ABBREVIATION",
                    "GP",
                    "MIN",
                    "PTS",
                    "PIE",
                ]
            ].drop_duplicates("name_key")
            if "PIE" in nba_traditional.columns
            else nba_traditional[["name_key", "PLAYER_ID", "TEAM_ABBREVIATION", "GP", "MIN", "PTS"]].drop_duplicates(
                "name_key"
            ),
            on="name_key",
            how="left",
        )

    nba_advanced = nba.get("nba_advanced")
    if nba_advanced is not None and "PLAYER_ID" in nba_advanced.columns and "PLAYER_ID" in merged.columns:
        cols = [c for c in ["PLAYER_ID", "PIE", "TS_PCT", "USG_PCT", "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE"] if c in nba_advanced.columns]
        merged = merged.merge(nba_advanced[cols].drop_duplicates("PLAYER_ID"), on="PLAYER_ID", how="left", suffixes=("", "_nba"))

    merged["player_name"] = merged["Player"]
    merged["player_id"] = [
        int(nba_id) if pd.notna(nba_id) else _stable_player_id(bbref_id, name)
        for nba_id, bbref_id, name in zip(
            merged["PLAYER_ID"] if "PLAYER_ID" in merged.columns else [None] * len(merged),
            merged["bbref_id"],
            merged["player_name"],
        )
    ]
    merged["season"] = SEASON
    merged["name_key"] = merged["player_name"].map(normalize_name)
    return merged


def run_ingest(*, skip_pbp: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    bbref = fetch_bbref_season()
    for name, frame in bbref.items():
        write_csv(RAW_DIR / f"{name}.csv", frame)

    nba = try_fetch_nba_official()
    for name, frame in nba.items():
        write_csv(RAW_DIR / f"{name}.csv", frame)

    if not skip_pbp:
        game_log = nba.get("nba_game_log")
        if game_log is None:
            logger.warning(
                "No NBA.com game log — play-by-play skipped. "
                "Run ingest on a network that can reach stats.nba.com to fill raw_data/pbp/."
            )
        else:
            extract_play_by_play(game_log)

    ratings = fetch_2k_ratings()
    write_csv(RAW_DIR / "nba_2k_ratings.csv", ratings)

    players = build_player_index(bbref, nba)
    write_csv(RAW_DIR / "players_raw.csv", players)

    manifest = {
        "season": SEASON,
        "generated_at": datetime.now(UTC).isoformat(),
        "sources": {
            "basketball_reference": True,
            "nba_api": sorted(nba.keys()),
            "nba_2k": True,
            "pbp_files": len(list((RAW_DIR / "pbp").glob("*.json"))) if (RAW_DIR / "pbp").exists() else 0,
        },
        "row_counts": {
            "players_raw": int(len(players)),
            "nba_2k_ratings": int(len(ratings)),
        },
    }
    (RAW_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Stage 1 complete. Manifest: %s", manifest)


if __name__ == "__main__":
    run_ingest()
