"""Stage 1 — Play-by-play from stats.nba.com (run this on a home network)."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd
from requests import exceptions as req_exc

from nba_ovr.settings import (
    NBA_API_TIMEOUT,
    PBP_MAX_FAILURES,
    PBP_MAX_GAMES,
    PBP_RETRY_ATTEMPTS,
    PBP_SLEEP_SECONDS,
    RAW_DIR,
    SEASON,
)

logger = logging.getLogger(__name__)


def _pbp_dir() -> Path:
    path = RAW_DIR / "pbp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _checkpoint_path(out_dir: Path) -> Path:
    return out_dir / "checkpoint.json"


def _load_checkpoint(out_dir: Path) -> dict:
    path = _checkpoint_path(out_dir)
    if not path.exists():
        return {"completed": [], "failed": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"completed": [], "failed": {}}
    data.setdefault("completed", [])
    data.setdefault("failed", {})
    return data


def _save_checkpoint(out_dir: Path, checkpoint: dict) -> None:
    _checkpoint_path(out_dir).write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")


def unique_game_ids(game_log: pd.DataFrame) -> list[str]:
    if game_log.empty or "GAME_ID" not in game_log.columns:
        return []
    ids = game_log["GAME_ID"].astype(str).drop_duplicates().tolist()
    ids.sort()
    if PBP_MAX_GAMES > 0:
        ids = ids[:PBP_MAX_GAMES]
    return ids


def is_retryable_pbp_error(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            TimeoutError,
            req_exc.Timeout,
            req_exc.ReadTimeout,
            req_exc.ConnectTimeout,
            req_exc.ConnectionError,
            req_exc.ProxyError,
            req_exc.ChunkedEncodingError,
        ),
    )


def fetch_play_by_play(game_id: str, *, timeout: int, retry_attempts: int, sleep_seconds: float) -> pd.DataFrame:
    from nba_api.stats.endpoints import playbyplayv2
    from nba_api.stats.library.http import NBAStatsHTTP

    NBAStatsHTTP.TIMEOUT = timeout
    last_error: Exception | None = None
    attempts = max(1, retry_attempts + 1)
    for attempt in range(1, attempts + 1):
        try:
            data = playbyplayv2.PlayByPlayV2(game_id=game_id, timeout=timeout)
            frame = data.get_data_frames()[0]
            frame["GAME_ID"] = game_id
            return frame
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            retryable = is_retryable_pbp_error(exc)
            if (not retryable) or attempt == attempts:
                raise
            wait = max(sleep_seconds, min(8.0, sleep_seconds * (2 ** (attempt - 1))))
            logger.warning(
                "Retryable PBP failure game=%s attempt=%s/%s error=%s wait=%.2fs",
                game_id,
                attempt,
                attempts,
                exc,
                wait,
            )
            time.sleep(wait)
    raise RuntimeError(f"PlayByPlayV2 failed for game {game_id}") from last_error


def extract_play_by_play(
    game_log: pd.DataFrame,
    *,
    max_failures: int = PBP_MAX_FAILURES,
    sleep_seconds: float = PBP_SLEEP_SECONDS,
    timeout: int = NBA_API_TIMEOUT,
    retry_attempts: int = PBP_RETRY_ATTEMPTS,
) -> Path:
    """Download PBP JSON per game with checkpoints so a rate-limit does not wipe progress."""
    out_dir = _pbp_dir()
    checkpoint = _load_checkpoint(out_dir)
    completed = set(checkpoint.get("completed", []))
    failed = checkpoint.setdefault("failed", {})
    game_ids = unique_game_ids(game_log)
    logger.info("Play-by-play target: %s games (PBP_MAX_GAMES=%s)", len(game_ids), PBP_MAX_GAMES)

    failures = 0
    for index, game_id in enumerate(game_ids, start=1):
        dest = out_dir / f"{game_id}.json"
        if dest.exists() or game_id in completed:
            continue
        try:
            frame = fetch_play_by_play(
                game_id,
                timeout=timeout,
                retry_attempts=retry_attempts,
                sleep_seconds=sleep_seconds,
            )
            dest.write_text(frame.to_json(orient="records"), encoding="utf-8")
            completed.add(game_id)
            failed.pop(game_id, None)
            checkpoint["completed"] = sorted(completed)
            _save_checkpoint(out_dir, checkpoint)
            if index % 10 == 0:
                logger.info("PBP %s/%s saved (%s events)", index, len(game_ids), len(frame))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            retryable = is_retryable_pbp_error(exc)
            failed[game_id] = {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "retryable": retryable,
                "failed_at_index": index,
            }
            checkpoint["failed"] = failed
            _save_checkpoint(out_dir, checkpoint)
            logger.warning("PBP failed for game %s (%s): %s", game_id, type(exc).__name__, exc)
            if failures >= max_failures:
                logger.error("Too many PBP failures — stopping early. Re-run later to resume.")
                break
        time.sleep(sleep_seconds)

    manifest = {
        "season": SEASON,
        "requested_games": len(game_ids),
        "saved_files": len(list(out_dir.glob("*.json"))),
        "failed_games": len(checkpoint.get("failed", {})),
        "timeout_seconds": timeout,
        "retry_attempts": retry_attempts,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out_dir
