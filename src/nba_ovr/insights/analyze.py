"""Stage 5 — overrated / underrated tables, PPG vs OVR scatter plots, Markdown report."""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from nba_ovr.reporting import dataframe_to_markdown
from nba_ovr.settings import GAME_VERSION, PROCESSED_DIR, REPORTS_DIR, SEASON

logger = logging.getLogger(__name__)


def _load_ovr() -> pd.DataFrame:
    path = PROCESSED_DIR / "true_ovr.csv"
    if not path.exists():
        raise FileNotFoundError("Brak processed_data/true_ovr.csv — uruchom Etap 4.")
    frame = pd.read_csv(path)
    return frame[frame["ovr_2k"].notna()].copy()


def _top_tables(frame: pd.DataFrame, n: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    cols = [
        c
        for c in [
            "player_name",
            "team_abbreviation",
            "position",
            "gp",
            "pts",
            "per",
            "ovr_2k",
            "true_ovr",
            "ovr_gap",
        ]
        if c in frame.columns
    ]
    overrated = frame.sort_values("ovr_gap", ascending=False).head(n)[cols]
    underrated = frame.sort_values("ovr_gap", ascending=True).head(n)[cols]
    return overrated, underrated


def _scatter(frame: pd.DataFrame, dest: Path) -> None:
    sns.set_theme(style="whitegrid", context="talk")
    fig, axes = plt.subplots(1, 2, figsize=(16, 7), sharey=False)

    left = axes[0]
    sns.scatterplot(data=frame, x="pts", y="ovr_2k", hue="position", ax=left, alpha=0.75, s=60, legend=False)
    left.set_title(f"{GAME_VERSION} OVR vs PPG")
    left.set_xlabel("Points per game")
    left.set_ylabel("Overall")

    right = axes[1]
    sns.scatterplot(data=frame, x="pts", y="true_ovr", hue="position", ax=right, alpha=0.75, s=60)
    right.set_title("True OVR vs PPG")
    right.set_xlabel("Points per game")
    right.set_ylabel("Overall")
    right.legend(title="Pos", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=10)

    fig.suptitle(f"Does 2K over-reward scoring?  ({SEASON} regular season)", y=1.02)
    fig.tight_layout()
    dest.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(dest, dpi=140, bbox_inches="tight")
    plt.close(fig)
    logger.info("Wrote %s", dest)


def _corr_line(frame: pd.DataFrame, y: str) -> str:
    subset = frame[["pts", y]].dropna()
    if len(subset) < 5:
        return "n/a"
    return f"{subset['pts'].corr(subset[y]):.3f}"


def _markdown(frame: pd.DataFrame, overrated: pd.DataFrame, underrated: pd.DataFrame) -> str:
    corr_2k = _corr_line(frame, "ovr_2k")
    corr_true = _corr_line(frame, "true_ovr")
    return f"""# True Analytics OVR vs {GAME_VERSION}

Season: **{SEASON}** regular season. Qualified players: GP ≥ 15 and MPG ≥ 10.

## How to read this

- **2K OVR** — current roster overall from 2kratings.com ({GAME_VERSION}).
- **True OVR** — heuristic overall from PER, TS%, BPM/VORP, usage×efficiency, and defensive rates.
- **OVR gap** = 2K − True. Positive ⇒ 2K is higher (overrated *relative to this model*). Negative ⇒ hidden gem.

This is a v1 model. The weights are in `src/nba_ovr/settings.py` — change them and re-run stages 4–5.

## Scoring bias check

Pearson correlation of PPG vs rating:

| Rating | corr(PPG, rating) |
| --- | --- |
| {GAME_VERSION} OVR | {corr_2k} |
| True OVR | {corr_true} |

If the left number is clearly larger, the video game is leaning on points more than the box-score impact stats.

![PPG vs OVR](ppg_vs_ovr.png)

## Top 10 overrated (2K ≫ True OVR)

{dataframe_to_markdown(overrated)}

## Top 10 underrated / hidden gems (True OVR ≫ 2K)

{dataframe_to_markdown(underrated)}

## Caveats

- Play-by-play defensive events are optional. If `raw_data/pbp/` is empty (stats.nba.com blocked), True OVR leans on BBRef STL/BLK per 100 and DBPM.
- 2K ratings include reputation, **potential**, and recency. High-school lottery wings will look “overrated” here on purpose: the model only sees this season’s box score.
- Backup centers with huge PER in 12–18 MPG used to spike True OVR; v1 shrinks composites by total minutes (`minutes_credibility`).
- A “gap” is not automatically a mistake by 2K.
- Name matching can miss two-way players and duplicate names. See `processed_data/unmatched_2k.csv`.
"""


def run_insights() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    frame = _load_ovr()
    overrated, underrated = _top_tables(frame)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    overrated.to_csv(REPORTS_DIR / "top_overrated.csv", index=False)
    underrated.to_csv(REPORTS_DIR / "top_underrated.csv", index=False)
    _scatter(frame, REPORTS_DIR / "ppg_vs_ovr.png")

    markdown = _markdown(frame, overrated, underrated)
    (REPORTS_DIR / "FINDINGS.md").write_text(markdown, encoding="utf-8")
    frame.sort_values("true_ovr", ascending=False).head(25)[
        [c for c in ["player_name", "pts", "per", "ovr_2k", "true_ovr", "ovr_gap"] if c in frame.columns]
    ].to_csv(REPORTS_DIR / "top_true_ovr.csv", index=False)
    logger.info("Stage 5 complete → %s", REPORTS_DIR / "FINDINGS.md")


if __name__ == "__main__":
    run_insights()
