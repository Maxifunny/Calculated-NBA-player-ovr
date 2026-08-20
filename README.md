# True Analytics OVR

Pipeline, który liczy własne **True OVR** zawodników NBA (skala 2K, ~62–99) i stawia je obok kart z **NBA 2K**, żeby znaleźć graczy **overrated** i **underrated**.

Sezon bazowy: **2025-26** (ostatni dokończony regular season na sierpień 2026) + oceny **2K26**.

Ten PR świadomie zostawia Ci testowanie. Spark jest sercem Etapu 2 — czytaj `docs/spark_nauka.md` przy pierwszym odpaleniu.

## Architektura

```
nba_api / Basketball-Reference / 2kratings
                │
                ▼
          raw_data/            Etap 1  Python ingest
                │
                ▼
        PySpark ETL            Etap 2  filtr + PBP + join 2K
                │
                ▼
     processed_data/*.parquet
                │
                ▼
     PostgreSQL / SQLite       Etap 3  players + advanced_stats + nba_2k_ratings
                │                  VIEW player_ovr_mart
                ▼
        heuristic True OVR     Etap 4  pandas + scikit-learn
                │
                ▼
     reports/FINDINGS.md       Etap 5  tabele + scatter PPG vs OVR
```

Nie trenujemy modelu na ocenach 2K. To by skopiowało bias gry (punkty, popularność). True OVR jest **heurystyką z jawnymi wagami** w `src/nba_ovr/settings.py` — to Ty decydujesz, czy wagi mają sens.

## Wymagania

- Python 3.10+
- JDK 17+ (do PySpark; na Ubuntu zwykle `openjdk-21-jdk`)
- Opcjonalnie Docker, jeśli chcesz PostgreSQL zamiast SQLite

```bash
python3 -m pip install -e ".[dev]"
cp .env.example .env
```

`stats.nba.com` (nba_api, play-by-play) często nie odpowiada z sieci chmurowych / datacenter. **Basketball-Reference + publiczne API 2K działają bez tego.** Play-by-play odpal u siebie w domu, bez `--skip-pbp`.

## Uruchamianie etapami (rekomendowane do nauki)

```bash
# 1. Surowe CSV w raw_data/
python3 -m nba_ovr ingest --skip-pbp
# lub (z PBP):
python3 -m nba_ovr ingest --pbp-provider nba_api --pbp-max-failures 12 --pbp-sleep 1.2 --nba-api-timeout 90

# 2. Spark: filtr GP/MPG, join 2K, zapis Parquet
python3 -m nba_ovr spark

# 3. Hurtownia SQL (domyślnie warehouse/nba_ovr.sqlite)
python3 -m nba_ovr sql

# 4. True OVR
python3 -m nba_ovr ovr

# 5. Raport do portfolio
python3 -m nba_ovr insights
```

Albo wszystko: `python3 -m nba_ovr all --skip-pbp` / `make all`.

Wyłączenie PBP bez `--skip-pbp`:

```bash
python3 -m nba_ovr ingest --pbp-provider none
```

PostgreSQL:

```bash
docker compose up -d
# w .env:
# DATABASE_URL=postgresql+psycopg2://nba:nba@localhost:5432/nba_ovr
python3 -m nba_ovr sql
```

## Co sprawdzić jako reviewer

1. `raw_data/manifest.json` — które źródła wstały.
2. `processed_data/unmatched_2k.csv` — kogo nie złączyliśmy z kartą 2K.
3. Log Sparka: ile zawodników odpada na filtrze 15 GP / 10 MPG. Zmień `MIN_GAMES` i odpal Etap 2 jeszcze raz.
4. `reports/FINDINGS.md` — czy Top overrated/underrated wygląda koszykarsko, czy model nagradza tylko PER.
5. Wagi w `OVR_WEIGHTS` — jeśli Twoim zdaniem defensywa jest za słaba, podnieś `dbpm` / `stocks_per_100` i zrób Etapy 4–5.

## Skąd dane

| Źródło | Po co |
| --- | --- |
| Basketball-Reference | PER, TS%, USG%, BPM, VORP, DWS, per-game, per-100 |
| nba_api (opcjonalnie) | PIE, ratingi NBA.com, play-by-play |
| api.nba2kapi.com (public) | current-roster OVR z 2kratings.com |

PIE nie istnieje na BBRef. Gdy nba_api nie wstanie, model podstawia VORP pod brakujący PIE.

## Testy

```bash
python3 -m pytest -q
```
