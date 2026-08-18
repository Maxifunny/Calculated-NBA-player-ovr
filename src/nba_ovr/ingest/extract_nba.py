"""Stage 1 — NBA.com stats via nba_api (optional; often blocked from cloud IPs)."""

from __future__ import annotations

import logging
import time

import pandas as pd

from nba_ovr.settings import NBA_API_TIMEOUT, SEASON, SEASON_TYPE

logger = logging.getLogger(__name__)


def _configure_nba_api() -> None:
    from nba_api.stats.library.http import NBAStatsHTTP

    NBAStatsHTTP.TIMEOUT = NBA_API_TIMEOUT


def _call(endpoint_cls, **kwargs) -> pd.DataFrame:
    _configure_nba_api()
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            data = endpoint_cls(timeout=NBA_API_TIMEOUT, **kwargs)
            return data.get_data_frames()[0]
        except Exception as exc:  # noqa: BLE001 — nba_api raises a mix of types
            last_error = exc
            wait = 2 ** attempt
            logger.warning("nba_api %s failed (%s). Retry in %ss", endpoint_cls.__name__, exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"nba_api endpoint {endpoint_cls.__name__} failed") from last_error


def fetch_league_dash(measure_type: str, per_mode: str = "PerGame") -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguedashplayerstats

    logger.info("Fetching NBA.com LeagueDashPlayerStats measure=%s season=%s", measure_type, SEASON)
    return _call(
        leaguedashplayerstats.LeagueDashPlayerStats,
        season=SEASON,
        season_type_all_star=SEASON_TYPE,
        measure_type_detailed_defense=measure_type,
        per_mode_detailed=per_mode,
    )


def fetch_estimated_metrics() -> pd.DataFrame:
    from nba_api.stats.endpoints import playerestimatedmetrics

    logger.info("Fetching NBA.com PlayerEstimatedMetrics season=%s", SEASON)
    return _call(
        playerestimatedmetrics.PlayerEstimatedMetrics,
        season=SEASON,
        season_type=SEASON_TYPE,
    )


def fetch_bio() -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguedashplayerbiostats

    logger.info("Fetching NBA.com player bio stats season=%s", SEASON)
    return _call(
        leaguedashplayerbiostats.LeagueDashPlayerBioStats,
        season=SEASON,
        season_type_all_star=SEASON_TYPE,
    )


def fetch_game_log() -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguegamelog

    logger.info("Fetching NBA.com LeagueGameLog season=%s", SEASON)
    return _call(
        leaguegamelog.LeagueGameLog,
        season=SEASON,
        season_type_all_star=SEASON_TYPE,
    )


def try_fetch_nba_official() -> dict[str, pd.DataFrame]:
    """Return whatever NBA.com endpoints succeed. Empty dict if the host is unreachable."""
    frames: dict[str, pd.DataFrame] = {}
    mapping = {
        "nba_traditional": lambda: fetch_league_dash("Base", "PerGame"),
        "nba_advanced": lambda: fetch_league_dash("Advanced", "PerGame"),
        "nba_defense": lambda: fetch_league_dash("Defense", "PerGame"),
        "nba_estimated": fetch_estimated_metrics,
        "nba_bio": fetch_bio,
        "nba_game_log": fetch_game_log,
    }
    first_name = next(iter(mapping))
    try:
        frames[first_name] = mapping[first_name]()
        logger.info("Loaded %s: %s rows", first_name, len(frames[first_name]))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "stats.nba.com unavailable (%s). Skipping remaining nba_api endpoints. "
            "Basketball-Reference + 2K ratings still complete Stage 1.",
            exc,
        )
        return {}

    for name, loader in list(mapping.items())[1:]:
        try:
            frames[name] = loader()
            logger.info("Loaded %s: %s rows", name, len(frames[name]))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping %s: %s", name, exc)
    return frames
