-- Data mart for the Data Science stage: one flat row per qualified player.

DROP VIEW IF EXISTS player_ovr_mart;

CREATE VIEW player_ovr_mart AS
SELECT
    p.player_id,
    p.bbref_id,
    p.player_name,
    p.team_abbreviation,
    p.position,
    p.age,
    p.season,
    s.gp,
    s.mpg,
    s.pts,
    s.ast,
    s.reb,
    s.per,
    s.ts_pct,
    s.usg_pct,
    s.bpm,
    s.obpm,
    s.dbpm,
    s.vorp,
    s.dws,
    s.ast_pct,
    s.pie,
    s.stocks_per_100,
    s.usage_efficiency,
    s.def_events_per_100,
    s.per_percentile,
    r.overall AS ovr_2k,
    r.game_version,
    r.team AS team_2k,
    r.position AS position_2k,
    r.name_match_score
FROM players AS p
JOIN advanced_stats AS s
  ON s.player_id = p.player_id
 AND s.season = p.season
LEFT JOIN nba_2k_ratings AS r
  ON r.player_id = p.player_id
 AND r.season = p.season;
