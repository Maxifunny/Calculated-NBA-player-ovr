"""Command-line entry: python -m nba_ovr.cli [stage|all]."""

from __future__ import annotations

import argparse
import logging
import sys

from nba_ovr.ingest.run import run_ingest
from nba_ovr.insights.analyze import run_insights
from nba_ovr.ovr.model import run_ovr
from nba_ovr.spark.etl import run_etl
from nba_ovr.warehouse.load import load_warehouse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="True Analytics OVR pipeline")
    parser.add_argument(
        "stage",
        choices=["ingest", "spark", "sql", "ovr", "insights", "all"],
        help="Which stage to run. `all` runs 1→5 in order.",
    )
    parser.add_argument("--skip-pbp", action="store_true", help="Stage 1: do not call stats.nba.com play-by-play")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.stage in ("ingest", "all"):
        run_ingest(skip_pbp=args.skip_pbp)
    if args.stage in ("spark", "all"):
        run_etl()
    if args.stage in ("sql", "all"):
        load_warehouse()
    if args.stage in ("ovr", "all"):
        run_ovr()
    if args.stage in ("insights", "all"):
        run_insights()
    return 0


if __name__ == "__main__":
    sys.exit(main())
