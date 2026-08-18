# Architecture notes

## Why three storage layers?

- `raw_data/` is immutable extracts. Re-run Spark without hitting the network.
- `processed_data/` is the analytic grain: one qualified player per row, Parquet + flat CSV.
- SQL is a governed schema (`players`, `advanced_stats`, `nba_2k_ratings`) plus `player_ovr_mart` so Stage 4 does not parse Spark catalogs.

## Grain

One row = one player in one regular season, after the rotation filter (default 15 GP and 10 MPG).

Traded players are collapsed to Basketball-Reference `TOT`.

## True OVR is not a 2K clone

Stage 4 maps a weighted robust-scaled composite onto a 2K-shaped curve (floor ~62, MVP ~99). Labels from 2K are used only for comparison, never as training targets.

Weights live in `nba_ovr.settings.OVR_WEIGHTS` and must sum to 1.0 (enforced by tests).
