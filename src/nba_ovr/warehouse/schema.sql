-- True Analytics OVR warehouse (PostgreSQL dialect)
-- SQLite used in this repo accepts the same CREATE TABLE statements with small caveats:
--   * SERIAL → INTEGER PRIMARY KEY AUTOINCREMENT  (the Python loader maps this)
--   * NUMERIC is stored as REAL/NUMERIC

CREATE TABLE IF NOT EXISTS players (
    player_id           INTEGER PRIMARY KEY,
    bbref_id            TEXT,
    player_name         TEXT NOT NULL,
    name_key            TEXT NOT NULL,
    team_abbreviation   TEXT,
    position            TEXT,
    age                 INTEGER,
    season              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS advanced_stats (
    player_id           INTEGER NOT NULL REFERENCES players (player_id),
    season              TEXT NOT NULL,
    gp                  INTEGER,
    mpg                 DOUBLE PRECISION,
    pts                 DOUBLE PRECISION,
    ast                 DOUBLE PRECISION,
    reb                 DOUBLE PRECISION,
    per                 DOUBLE PRECISION,
    ts_pct              DOUBLE PRECISION,
    usg_pct             DOUBLE PRECISION,
    bpm                 DOUBLE PRECISION,
    obpm                DOUBLE PRECISION,
    dbpm                DOUBLE PRECISION,
    vorp                DOUBLE PRECISION,
    dws                 DOUBLE PRECISION,
    ast_pct             DOUBLE PRECISION,
    pie                 DOUBLE PRECISION,
    stocks_per_100      DOUBLE PRECISION,
    usage_efficiency    DOUBLE PRECISION,
    def_events_per_100  DOUBLE PRECISION,
    per_percentile      DOUBLE PRECISION,
    PRIMARY KEY (player_id, season)
);

CREATE TABLE IF NOT EXISTS nba_2k_ratings (
    player_id           INTEGER REFERENCES players (player_id),
    player_name         TEXT,
    overall             INTEGER,
    position            TEXT,
    team                TEXT,
    slug                TEXT,
    game_version        TEXT,
    name_match_score    DOUBLE PRECISION,
    season              TEXT NOT NULL,
    PRIMARY KEY (player_id, season, game_version)
);

CREATE INDEX IF NOT EXISTS idx_players_name_key ON players (name_key);
CREATE INDEX IF NOT EXISTS idx_advanced_season ON advanced_stats (season);
CREATE INDEX IF NOT EXISTS idx_2k_overall ON nba_2k_ratings (overall);
