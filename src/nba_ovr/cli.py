"""Command-line entry: python -m nba_ovr.cli [stage|all]."""

from __future__ import annotations

import argparse
import logging
import sys

from nba_ovr.ingest.run import run_ingest
from nba_ovr.insights.analyze import run_insights
from nba_ovr.ovr.model import run_ovr
from nba_ovr.settings import NBA_API_TIMEOUT, PBP_MAX_FAILURES, PBP_PROVIDER, PBP_RETRY_ATTEMPTS, PBP_SLEEP_SECONDS
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
    parser.add_argument(
        "--pbp-provider",
        choices=["nba_api", "none"],
        default=PBP_PROVIDER,
        help="Stage 1: play-by-play provider. Use 'none' to disable PBP calls.",
    )
    parser.add_argument(
        "--pbp-max-failures",
        type=int,
        default=PBP_MAX_FAILURES,
        help="Stage 1: stop PBP after N failed games.",
    )
    parser.add_argument(
        "--pbp-sleep",
        type=float,
        default=PBP_SLEEP_SECONDS,
        help="Stage 1: sleep seconds between PBP calls.",
    )
    parser.add_argument(
        "--nba-api-timeout",
        type=int,
        default=NBA_API_TIMEOUT,
        help="nba_api timeout in seconds for Stage 1.",
    )
    parser.add_argument(
        "--pbp-retry-attempts",
        type=int,
        default=PBP_RETRY_ATTEMPTS,
        help="Stage 1: retry attempts for retryable PBP network failures.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.stage in ("ingest", "all"):
        run_ingest(
            skip_pbp=args.skip_pbp,
            pbp_provider=args.pbp_provider,
            pbp_max_failures=args.pbp_max_failures,
            pbp_sleep=args.pbp_sleep,
            pbp_timeout=args.nba_api_timeout,
            pbp_retry_attempts=args.pbp_retry_attempts,
        )
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
