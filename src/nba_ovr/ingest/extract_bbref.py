"""Stage 1 — Basketball-Reference season tables (PER, BPM, VORP live here, not on NBA.com)."""

from __future__ import annotations

import logging
import re
from io import StringIO

import pandas as pd
from bs4 import BeautifulSoup

from nba_ovr.ingest.http_utils import request_with_retry
from nba_ovr.settings import SEASON_END_YEAR

logger = logging.getLogger(__name__)

_PLAYER_HREF = re.compile(r"/players/[a-z]/([a-z0-9]+)\.html", re.I)


def _table_url(stat_type: str) -> str:
    return f"https://www.basketball-reference.com/leagues/NBA_{SEASON_END_YEAR}_{stat_type}.html"


def _parse_player_id(href: str | None) -> str | None:
    if not href:
        return None
    match = _PLAYER_HREF.search(href)
    return match.group(1) if match else None


def scrape_bbref_table(stat_type: str) -> pd.DataFrame:
    """Download one BBRef season table and keep the Basketball-Reference player id."""
    url = _table_url(stat_type)
    logger.info("Scraping %s", url)
    response = request_with_retry(url, timeout=60)
    soup = BeautifulSoup(response.text, "lxml")

    table = soup.find("table", id=stat_type)
    if table is None:
        # Some pages wrap the table; fall back to the first data table.
        table = soup.find("table")
    if table is None:
        raise RuntimeError(f"No table found on {url}")

    html_table = StringIO(str(table))
    frame = pd.read_html(html_table)[0]
    frame.columns = [
        str(col[-1] if isinstance(col, tuple) else col).strip()
        for col in frame.columns
    ]

    player_ids: list[str | None] = []
    body = table.find("tbody")
    rows = body.find_all("tr") if body else []
    for row in rows:
        if "thead" in row.get("class", []) or row.get("class") == ["thead"]:
            player_ids.append(None)
            continue
        anchor = row.find("a", href=_PLAYER_HREF)
        player_ids.append(_parse_player_id(anchor["href"]) if anchor else None)

    # Header repeats inside the body — drop those before aligning ids.
    if "Player" in frame.columns:
        frame = frame[frame["Player"].astype(str) != "Player"].copy()
    if "Rk" in frame.columns:
        frame = frame[frame["Rk"].astype(str) != "Rk"].copy()

    # read_html keeps thead-repeat rows that BeautifulSoup tbody also contains.
    # Rebuild ids from remaining tbody rows that are not section headers.
    clean_ids: list[str | None] = []
    for row in rows:
        classes = row.get("class") or []
        if "thead" in classes:
            continue
        if row.find("th", {"scope": "col"}):
            continue
        anchor = row.find("a", href=_PLAYER_HREF)
        if not row.find("td"):
            continue
        clean_ids.append(_parse_player_id(anchor["href"]) if anchor else None)

    if len(clean_ids) == len(frame):
        frame.insert(0, "bbref_id", clean_ids)
    else:
        logger.warning(
            "bbref_id alignment mismatch for %s (%s ids vs %s rows) — matching by order truncated",
            stat_type,
            len(clean_ids),
            len(frame),
        )
        frame.insert(0, "bbref_id", (clean_ids + [None] * len(frame))[: len(frame)])

    frame["stat_type"] = stat_type
    return frame.reset_index(drop=True)


def collapse_traded_players(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the TOT row for traded players, otherwise the stint with the most games."""
    if "Player" not in frame.columns:
        return frame
    team_col = "Tm" if "Tm" in frame.columns else "Team"
    games_col = "G" if "G" in frame.columns else None

    def pick(group: pd.DataFrame) -> pd.Series:
        if team_col in group.columns:
            tot = group[group[team_col].astype(str).str.upper() == "TOT"]
            if not tot.empty:
                return tot.iloc[0]
        if games_col and games_col in group.columns:
            numeric_g = pd.to_numeric(group[games_col], errors="coerce")
            return group.loc[numeric_g.idxmax()]
        return group.iloc[0]

    id_col = "bbref_id" if frame["bbref_id"].notna().any() else "Player"
    pieces = [pick(group) for _, group in frame.groupby(id_col, dropna=False)]
    return pd.DataFrame(pieces).reset_index(drop=True)


def fetch_bbref_season() -> dict[str, pd.DataFrame]:
    tables = {}
    for stat_type in ("per_game", "advanced", "per_poss"):
        raw = scrape_bbref_table(stat_type)
        tables[f"bbref_{stat_type}"] = collapse_traded_players(raw)
        logger.info("BBRef %s: %s players", stat_type, len(tables[f"bbref_{stat_type}"]))
    return tables
