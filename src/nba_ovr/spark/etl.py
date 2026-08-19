"""
Etap 2 — PySpark ETL.

Ten plik jest celowo „gadatliwy”: każdy krok tłumaczy CO robi Spark i DLACZEGO.
Uruchom najpierw sam ten skrypt (po Etapie 1) i czytaj logi. Potem zmień
MIN_GAMES / MIN_MPG w settings.py i zobacz, jak kurczy się zbiór.

Pojęcia, które warto złapać przy pierwszym odpaleniu:
  * SparkSession  — wejście do klastra (u nas: lokalny proces, master=local[*])
  * DataFrame     — leniwa tabela; nic się nie liczy, dopóki nie wywołasz AKCJI
  * Transformacja — filter, select, groupBy, join (plan, jeszcze bez I/O)
  * Akcja         — count, show, write, collect (tu Spark naprawdę pracuje)
  * Parquet       — kolumnowy format; Spark czyta tylko potrzebne kolumny
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from nba_ovr.names import best_name_match, normalize_name
from nba_ovr.settings import (
    MIN_GAMES,
    MIN_MINUTES_PER_GAME,
    PROCESSED_DIR,
    RAW_DIR,
    SEASON,
)

logger = logging.getLogger(__name__)

# NBA.com event codes (PlayByPlayV2). Trzymamy je w jednym miejscu.
EVENT_MISSED_SHOT = 2
EVENT_REBOUND = 4
EVENT_TURNOVER = 5
EVENT_FOUL = 6


def _sanitize_column(name: str) -> str:
    """Spark i SQL nie lubią '%' ani spacji w nazwach kolumn."""
    cleaned = name.strip().replace("%", "_pct").replace("/", "_").replace("+", "_plus_")
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_").lower()
    if cleaned and cleaned[0].isdigit():
        cleaned = f"c_{cleaned}"
    return cleaned or "col"


def build_spark(app_name: str = "nba-true-ovr-etl") -> SparkSession:
    """Lokalny Spark: zużywa wszystkie rdzenie maszyny, na której odpalasz skrypt."""
    os.environ.setdefault("JAVA_HOME", os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-21-openjdk-amd64"))
    # Spark 4.x honoruje SPARK_LOCAL_IP; w kontenerach 127.0.0.1 bywa bezpieczniejsze.
    os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")

    spark = (
        SparkSession.builder.appName(app_name)
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        # Mały zbiór sezonowy nie potrzebuje 200 partycji shuffle (domyślna Spark).
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.ui.enabled", "false")
        .config("spark.driver.memory", os.getenv("SPARK_DRIVER_MEMORY", "2g"))
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    logger.info("Spark %s, master=%s", spark.version, spark.sparkContext.master)
    return spark


def _read_csv(spark: SparkSession, path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Brak pliku z Etapu 1: {path}. Uruchom najpierw: python -m nba_ovr.ingest.run")
    # header + inferSchema: wygodne na start. Na większych zbiorach podaje się schemat ręcznie.
    frame = spark.read.option("header", True).option("inferSchema", True).csv(str(path))
    for column in frame.columns:
        frame = frame.withColumnRenamed(column, _sanitize_column(column))
    return frame


def filter_rotation_noise(players):
    """Wyrzuca szum: 10-dniowe kontrakty i garbage-time specialists.

    GP i MP pochodzą z Basketball-Reference (kolumny g, mp po sanitizacji).
    To jest TRANSFORMACJA — Spark jeszcze nic nie liczy.
    """
    games = F.col("g").cast("double")
    mpg = F.col("mp").cast("double")
    filtered = players.filter(games.isNotNull() & mpg.isNotNull()).filter(
        (games >= F.lit(MIN_GAMES)) & (mpg >= F.lit(MIN_MINUTES_PER_GAME))
    )
    return filtered


def aggregate_play_by_play(spark: SparkSession):
    """Zdarzenia play-by-play → jedna linia na zawodnika.

    Niestandardowa metryka:
      def_events_per_100 ≈ (steals + blocks + defensive rebounds) / estimated possessions * 100

    Posiadania szacujemy z PBP: zbiórki + strzały + straty to grube przybliżenie
    (prawdziwe possession accounting jest trudniejsze). Dlatego metryka jest
    UZUPEŁNIENIEM BBRef STL%/BLK%, a nie jedynym filarem OVR.
    """
    pbp_dir = RAW_DIR / "pbp"
    files = list(pbp_dir.glob("*.json")) if pbp_dir.exists() else []
    files = [p for p in files if p.name != "manifest.json"]
    if not files:
        logger.warning("Brak raw_data/pbp/*.json — pomijam agregację PBP (Spark i tak dowiezie resztę).")
        return None

    logger.info("Czytam %s plików PBP (JSON). To jest ten 'big data' kawałek pipeline'u.", len(files))
    # Każdy plik to tablica eventów jednego meczu. mergeSchema=false, bo schemat NBA.com jest stały.
    pbp = spark.read.option("multiLine", True).json([str(p) for p in files])

    # Normalizacja nazw kolumn (NBA.com bywa niekonsekwentne w kapitalizacji).
    rename_map = {c: c.upper() for c in pbp.columns}
    for old, new in rename_map.items():
        if old != new:
            pbp = pbp.withColumnRenamed(old, new)

    for required in ("EVENTMSGTYPE", "PLAYER1_ID", "PLAYER2_ID", "PLAYER3_ID"):
        if required not in pbp.columns:
            logger.warning("PBP nie ma kolumny %s — pomijam agregację.", required)
            return None

    descriptions = F.concat_ws(
        " ",
        F.coalesce(F.col("HOMEDESCRIPTION"), F.lit("")),
        F.coalesce(F.col("VISITORDESCRIPTION"), F.lit("")),
        F.coalesce(F.col("NEUTRALDESCRIPTION"), F.lit("")),
    )
    desc_upper = F.upper(descriptions)

    events = (
        pbp.withColumn("event_type", F.col("EVENTMSGTYPE").cast("int"))
        .withColumn("p1", F.col("PLAYER1_ID").cast("bigint"))
        .withColumn("p2", F.col("PLAYER2_ID").cast("bigint"))
        .withColumn("p3", F.col("PLAYER3_ID").cast("bigint"))
        .withColumn("is_steal", (F.col("event_type") == EVENT_TURNOVER) & (F.col("p2") > 0))
        .withColumn(
            "is_block",
            (F.col("event_type") == EVENT_MISSED_SHOT) & desc_upper.contains("BLOCK") & (F.col("p3") > 0),
        )
        .withColumn(
            "is_dreb",
            (F.col("event_type") == EVENT_REBOUND) & desc_upper.contains("DEFENSIVE REBOUND") & (F.col("p1") > 0),
        )
        .withColumn(
            "is_charge",
            (F.col("event_type") == EVENT_FOUL) & desc_upper.contains("CHARGE") & (F.col("p2") > 0),
        )
        .withColumn("is_tov", (F.col("event_type") == EVENT_TURNOVER) & (F.col("p1") > 0))
        .withColumn(
            "is_fga",
            F.col("event_type").isin(1, EVENT_MISSED_SHOT) & (F.col("p1") > 0),
        )
    )

    # Trzy „role” w evencie: aktor (p1), odbiorca (p2, np. steal), trzeci (p3, np. block).
    steals = events.filter(F.col("is_steal")).groupBy(F.col("p2").alias("player_id")).agg(F.count("*").alias("pbp_stl"))
    blocks = events.filter(F.col("is_block")).groupBy(F.col("p3").alias("player_id")).agg(F.count("*").alias("pbp_blk"))
    drebs = events.filter(F.col("is_dreb")).groupBy(F.col("p1").alias("player_id")).agg(F.count("*").alias("pbp_dreb"))
    charges = events.filter(F.col("is_charge")).groupBy(F.col("p2").alias("player_id")).agg(
        F.count("*").alias("pbp_charges_drawn")
    )
    tov = events.filter(F.col("is_tov")).groupBy(F.col("p1").alias("player_id")).agg(F.count("*").alias("pbp_tov"))
    fga = events.filter(F.col("is_fga")).groupBy(F.col("p1").alias("player_id")).agg(F.count("*").alias("pbp_fga"))

    players = (
        steals.join(blocks, "player_id", "full")
        .join(drebs, "player_id", "full")
        .join(charges, "player_id", "full")
        .join(tov, "player_id", "full")
        .join(fga, "player_id", "full")
        .na.fill(0)
    )

    # Szacunek posiadania na zawodnika: FGA + TOV — 0.44*FTA pomijamy (PBP FT jest osobnym eventem).
    # To celowo proste: łatwiej to później poprawić, niż udawać, że mamy tracking Second Spectrum.
    players = players.withColumn(
        "pbp_est_poss",
        F.greatest(F.col("pbp_fga") + F.col("pbp_tov"), F.lit(1.0)),
    ).withColumn(
        "def_events_per_100",
        (F.col("pbp_stl") + F.col("pbp_blk") + F.col("pbp_dreb") + F.col("pbp_charges_drawn"))
        / F.col("pbp_est_poss")
        * F.lit(100.0),
    )
    return players


def _build_2k_lookup(ratings_pdf) -> dict[str, dict]:
    """Fuzzy matching robimy na DRIVERZE (mały zbiór ~600 kart 2K), potem broadcast join.

    To ważny wzorzec Spark: ciężkie, Pythonowe rzeczy na małym zbiorze → mapa;
    duży zbiór łączysz już w Spark SQL.
    """
    lookup: dict[str, dict] = {}
    for row in ratings_pdf.itertuples(index=False):
        key = normalize_name(getattr(row, "player_name", None) or getattr(row, "PLAYER_NAME", None))
        if not key:
            continue
        lookup[key] = {
            "ovr_2k": int(row.overall) if row.overall is not None else None,
            "team_2k": getattr(row, "team", None),
            "position_2k": getattr(row, "position", None),
            "slug_2k": getattr(row, "slug", None),
        }
    return lookup


def attach_2k_ratings(spark: SparkSession, players, ratings):
    # Use Pandas for the fuzzy join. On this pipeline scale (≈400 players),
    # it is fast and avoids a brittle Spark↔Python matching path.
    ratings_pdf = ratings.select("player_name", "overall", "team", "position", "slug").toPandas()
    lookup = _build_2k_lookup(ratings_pdf)
    candidate_keys = list(lookup.keys())

    player_pdf = players.toPandas()

    # Be defensive: if Stage 1 wasn't run (or wrong file is present),
    # required columns may be missing (common on fresh Windows setups).
    if "player_id" not in player_pdf.columns:
        raise RuntimeError(
            "Brak kolumny 'player_id' w players DataFrame. "
            "Upewnij się, że uruchomiłeś Etap 1: `python -m nba_ovr ingest --skip-pbp` "
            "i masz plik raw_data/players_raw.csv."
        )

    # Stage 1 should provide player_name + name_key, but if not, compute it.
    if "player_name" not in player_pdf.columns:
        alt = next((c for c in ("Player", "PLAYER_NAME", "player") if c in player_pdf.columns), None)
        if alt:
            player_pdf["player_name"] = player_pdf[alt]
        else:
            raise RuntimeError(
                "Brak kolumny 'player_name' w players DataFrame. "
                "Sprawdź poprawność pliku raw_data/players_raw.csv."
            )
    if "name_key" not in player_pdf.columns:
        player_pdf["name_key"] = player_pdf["player_name"].map(normalize_name)

    rows = []
    unmatched = []
    for rec in player_pdf.to_dict(orient="records"):
        player_id = int(rec["player_id"])
        player_name = rec.get("player_name") or ""
        key = rec.get("name_key") or normalize_name(player_name)

        match_key = key if key in lookup else None
        score = 100.0 if match_key else 0.0
        if match_key is None:
            fuzzy = best_name_match(key, candidate_keys, score_cutoff=88)
            if fuzzy:
                match_key, score = fuzzy

        if match_key is None:
            unmatched.append(
                {"player_id": player_id, "player_name": player_name, "name_key": key}
            )
            continue

        payload = lookup[match_key]
        rows.append(
            {
                "player_id": player_id,
                "ovr_2k": payload["ovr_2k"],
                "team_2k": payload["team_2k"],
                "position_2k": payload["position_2k"],
                "slug_2k": payload["slug_2k"],
                "name_match_score": score,
            }
        )

    unmatched_path = PROCESSED_DIR / "unmatched_2k.csv"
    import pandas as pd

    pd.DataFrame(unmatched).to_csv(unmatched_path, index=False)
    logger.info("2K match: %s dopasowanych, %s bez karty 2K (%s)", len(rows), len(unmatched), unmatched_path)

    if not rows:
        return players.withColumn("ovr_2k", F.lit(None).cast("int"))

    mapping = spark.createDataFrame(pd.DataFrame(rows))
    # Broadcast hint: prawa strona jest mała. Spark może i tak to zgadnąć, ale hint jest czytelny.
    return players.join(F.broadcast(mapping), on="player_id", how="left")


def add_helper_metrics(players):
    """Metryki, których Data Science potrzebuje później — liczmy je raz, w Spark."""

    def num(*names):
        for name in names:
            if name in players.columns:
                return F.col(name).cast("double")
        return F.lit(None).cast("double")

    per = num("adv_per", "per")
    ts = num("adv_ts_pct", "ts_pct", "adv_ts")
    usg = num("adv_usg_pct", "usg_pct")
    bpm = num("adv_bpm", "bpm")
    obpm = num("adv_obpm", "obpm")
    dbpm = num("adv_dbpm", "dbpm")
    vorp = num("adv_vorp", "vorp")
    dws = num("adv_dws", "dws")
    ast_pct = num("adv_ast_pct", "ast_pct")
    pie = num("pie", "adv_pie")
    stl100 = num("poss_stl", "adv_stl_pct")
    blk100 = num("poss_blk", "adv_blk_pct")
    pts = num("pg_pts", "pts")
    ast = num("pg_ast", "ast")
    reb = num("pg_trb", "trb", "reb")
    gp = num("g", "gp")
    mpg = num("mp", "min")

    stocks = F.coalesce(stl100, F.lit(0.0)) + F.coalesce(blk100, F.lit(0.0))
    usage_efficiency = F.coalesce(ts, F.lit(0.0)) * F.coalesce(usg, F.lit(0.0))

    pos_col = F.col("pos") if "pos" in players.columns else F.lit(None).cast("string")
    pos_2k = F.col("position_2k") if "position_2k" in players.columns else F.lit(None).cast("string")
    team_col = None
    for candidate in ("team_abbreviation", "tm", "team"):
        if candidate in players.columns:
            team_col = F.col(candidate)
            break
    if team_col is None:
        team_col = F.lit(None).cast("string")
    team_2k = F.col("team_2k") if "team_2k" in players.columns else F.lit(None).cast("string")

    out = (
        players.withColumn("per", per)
        .withColumn("ts_pct", ts)
        .withColumn("usg_pct", usg)
        .withColumn("bpm", bpm)
        .withColumn("obpm", obpm)
        .withColumn("dbpm", dbpm)
        .withColumn("vorp", vorp)
        .withColumn("dws", dws)
        .withColumn("ast_pct", ast_pct)
        .withColumn("pie", pie)
        .withColumn("pts", pts)
        .withColumn("ast", ast)
        .withColumn("reb", reb)
        .withColumn("gp", gp)
        .withColumn("mpg", mpg)
        .withColumn("stocks_per_100", stocks)
        .withColumn("usage_efficiency", usage_efficiency)
        .withColumn("position", F.coalesce(pos_col, pos_2k))
        .withColumn("team_abbreviation", F.coalesce(team_col, team_2k))
        .withColumn("season", F.lit(SEASON))
    )

    if "def_events_per_100" not in out.columns:
        out = out.withColumn("def_events_per_100", F.lit(None).cast("double"))

    # Percentile w obrębie sezonu — Window to klasyka Sparka, warta zrozumienia.
    window = Window.partitionBy("season").orderBy(F.col("per").asc_nulls_first())
    out = out.withColumn("per_percentile", F.percent_rank().over(window))
    return out


def write_outputs(players) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    parquet_dir = PROCESSED_DIR / "players_clean.parquet"
    spark_csv_dir = PROCESSED_DIR / "players_clean_spark.csv"

    # coalesce(1) = jeden plik CSV, wygodny do wglądu. Na terabajtach NIE rób tego.
    #
    # Na Windowsie zapis Parquet czasem wywala się z powodów środowiskowych
    # (uprawnienia / file-lock / kompatybilność). Nie blokujemy ETL:
    # jeśli Parquet nie zapisze się, i tak zapisujemy CSV, żeby Etap 3–5 poszły.
    if parquet_dir.exists():
        import shutil

        shutil.rmtree(parquet_dir, ignore_errors=True)

    parquet_ok = False
    try:
        (
            players.write.mode("overwrite")
            .option("compression", "snappy")
            .parquet(str(parquet_dir))
        )
        parquet_ok = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Zapis Parquet się nie udał (%s). Lecimy z CSV.", exc)
    (
        players.coalesce(1)
        .write.mode("overwrite")
        .option("header", True)
        .csv(str(spark_csv_dir))
    )
    if parquet_ok:
        logger.info("Zapisano Parquet → %s", parquet_dir)
    logger.info("Zapisano CSV Spark → %s", spark_csv_dir)


def flatten_spark_csv(csv_dir: Path, dest_name: str = "players_clean.csv") -> Path:
    """Spark zapisuje katalog CSV. Dla Etapu 3 zostawiamy też pojedynczy plik."""
    parts = list(csv_dir.glob("part-*.csv"))
    if not parts:
        raise FileNotFoundError(f"Spark nie zapisał part-*.csv w {csv_dir}")
    target = PROCESSED_DIR / dest_name
    target.write_text(parts[0].read_text(encoding="utf-8"), encoding="utf-8")
    logger.info("Płaski CSV → %s", target)
    return target


def run_etl() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    spark = build_spark()
    try:
        raw_players = _read_csv(spark, RAW_DIR / "players_raw.csv")
        if "player_id" in raw_players.columns:
            raw_players = raw_players.withColumn("player_id", F.col("player_id").cast("bigint"))
        ratings = _read_csv(spark, RAW_DIR / "nba_2k_ratings.csv")

        before = raw_players.count()  # AKCJA — tu Spark pierwszy raz materializuje plan
        rotation = filter_rotation_noise(raw_players)
        after = rotation.count()
        logger.info("Filtr rotacji: %s → %s zawodników (GP>=%s, MPG>=%s)", before, after, MIN_GAMES, MIN_MINUTES_PER_GAME)

        pbp_agg = aggregate_play_by_play(spark)
        if pbp_agg is not None:
            rotation = rotation.join(
                pbp_agg,
                rotation.player_id == pbp_agg.player_id,
                how="left",
            ).drop(pbp_agg.player_id)

        with_2k = attach_2k_ratings(spark, rotation, ratings)
        modeled = add_helper_metrics(with_2k)

        keep = [
            "player_id",
            "bbref_id",
            "player_name",
            "name_key",
            "season",
            "team_abbreviation",
            "position",
            "age",
            "gp",
            "mpg",
            "pts",
            "ast",
            "reb",
            "per",
            "ts_pct",
            "usg_pct",
            "bpm",
            "obpm",
            "dbpm",
            "vorp",
            "dws",
            "ast_pct",
            "pie",
            "stocks_per_100",
            "usage_efficiency",
            "def_events_per_100",
            "per_percentile",
            "ovr_2k",
            "team_2k",
            "position_2k",
            "slug_2k",
            "name_match_score",
        ]
        existing = [c for c in keep if c in modeled.columns]
        slim = modeled.select(*existing)

        write_outputs(slim)
        flatten_spark_csv(PROCESSED_DIR / "players_clean_spark.csv")

        summary = {
            "season": SEASON,
            "rows_in": before,
            "rows_out": slim.count(),
            "with_2k": slim.filter(F.col("ovr_2k").isNotNull()).count(),
        }
        (PROCESSED_DIR / "etl_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        logger.info("Stage 2 complete: %s", summary)
        slim.orderBy(F.col("per").desc_nulls_last()).show(10, truncate=False)
    finally:
        spark.stop()


if __name__ == "__main__":
    run_etl()
