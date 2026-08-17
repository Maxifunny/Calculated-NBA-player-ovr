"""Shared HTTP helpers with retries — NBA.com and BBRef both rate-limit aggressively."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

from nba_ovr.settings import HTTP_USER_AGENT

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": HTTP_USER_AGENT,
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def request_with_retry(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = 45,
    max_attempts: int = 5,
    backoff: float = 1.5,
) -> requests.Response:
    merged = {**DEFAULT_HEADERS, **(headers or {})}
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(url, headers=merged, params=params, timeout=timeout)
            if response.status_code == 429:
                wait = backoff * attempt * 2
                logger.warning("HTTP 429 for %s — sleeping %.1fs", url, wait)
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            wait = backoff ** attempt
            logger.warning(
                "Attempt %s/%s failed for %s (%s). Retry in %.1fs",
                attempt,
                max_attempts,
                url,
                exc,
                wait,
            )
            time.sleep(wait)
    raise RuntimeError(f"Failed to GET {url} after {max_attempts} attempts") from last_error


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, frame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    logger.info("Wrote %s (%s rows)", path, len(frame))
