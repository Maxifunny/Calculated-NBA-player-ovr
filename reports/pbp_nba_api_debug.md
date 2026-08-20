# PBP nba_api debug report (stats.nba.com)

Data testu: 2026-08-19 (cloud agent)

## Zakres testu minimalnego

1. Próba pobrania `LeagueGameLog` dla sezonu `2025-26` (timeout=30s), żeby wybrać szybkie `game_id`.
2. Gdy `LeagueGameLog` nie działa, fallback do 3 znanych ID:
   - `0022500001`
   - `0022500002`
   - `0022500003`
3. Dla każdego ID: `playbyplayv2.PlayByPlayV2(game_id=..., timeout=30)` + log statusu, czasu i błędu.

Wynik surowy zapisano w: `reports/pbp_debug_results.json`.

## Wyniki per game_id

| game_id | status | exception type | elapsed (s) | HTTP status |
| --- | --- | --- | ---: | --- |
| 0022500001 | failed | ReadTimeout | 30.148 | n/a |
| 0022500002 | failed | ReadTimeout | 30.137 | n/a |
| 0022500003 | failed | ReadTimeout | 30.129 | n/a |

## Dodatkowe obserwacje z uruchomienia

- `LeagueGameLog` również padł na `ReadTimeout` po 30 sekundach.
- W logu `nba_api` pojawiło się ostrzeżenie deprecacji:
  - `PlayByPlayV2 is deprecated ... nba_api issue #591`
  - To wskazuje dodatkowe ryzyko jakości danych nawet gdy endpoint odpowiada (w części środowisk V2 zwraca puste payloady).

## Diagnoza: local vs cloud

### Cloud (wynik z tego runu)

- Dominują timeouty sieciowe do `stats.nba.com` (`ReadTimeout`, brak kodu HTTP).
- Nie zaobserwowano 403 ani jawnego rate-limit (429) w tym przebiegu.
- Problem objawia się jako brak odpowiedzi hosta (lub silne opóźnienie/blackholing) z IP datacenter.

### Local (wniosek operacyjny)

Na typowej sieci domowej `stats.nba.com` zwykle odpowiada częściej niż z cloud/DC. PBP przechodzi stabilniej gdy:

- ruch wychodzi z residential IP,
- timeout jest podniesiony (`NBA_API_TIMEOUT` 60–120),
- requests są spowolnione (`PBP_SLEEP_SECONDS` 1.0–2.0),
- błędy retrywalne (timeout/connection reset) mają ograniczony retry z backoff.

## Klasyfikacja przyczyny (wg kategorii)

- **Rate limit:** niepotwierdzony w tym runie (brak 429).
- **IP block / 403:** niepotwierdzony w tym runie (brak 403).
- **Timeout:** **potwierdzony** (3/3 PBP + LeagueGameLog timeout).
- **Token/headers:** brak przesłanek na auth/token issue; to public endpoint. Bardziej wygląda na warstwę sieci/IP.

## Zmiany w kodzie ingest (wdrożone)

1. Parametryzacja PBP przez env/CLI:
   - `--pbp-provider nba_api|none`
   - `--pbp-max-failures`
   - `--pbp-sleep`
   - `--nba-api-timeout`
   - `--pbp-retry-attempts`
2. Retry tylko dla błędów retrywalnych (timeout/connection/proxy/chunked).
3. Checkpoint postępu i błędów:
   - `raw_data/pbp/checkpoint.json` (`completed` + `failed`) dla bezpiecznego resume.
4. Manifest PBP rozszerzony o:
   - `failed_games`, `timeout_seconds`, `retry_attempts`.

## Propozycja architektoniczna (defensywna)

1. **PBP optional by design**:
   - traktuj PBP jako enrichment, nie warunek pipeline’u.
   - domyślnie w cloud uruchamiaj `--pbp-provider none`.
2. **Fallback modelu bez PBP**:
   - gdy brak PBP, licz defensywę z BBRef (`DBPM`, `DWS`, `stocks_per_100`) + opcjonalnie `estimated` jeśli dostępne.
3. **Opcjonalny fallback źródła PBP**:
   - warstwa providerów (`nba_api`, później np. BBRef-PBP parser), żeby degradacja była kontrolowana.

## Root causes (1–3)

1. **Niestabilna/odcinana łączność cloud → stats.nba.com** (timeouty bez HTTP status).
2. **Wrażliwość endpointu PBP na środowisko/IP i pacing zapytań** (potrzebny sleep + retry).
3. **Ryzyko deprecacji `PlayByPlayV2`** (nawet przy dostępności sieci endpoint V2 bywa niekompletny/pusty).

## Co ustawić, żeby stabilizować pobieranie (tam gdzie się da)

W `.env`:

```env
NBA_API_TIMEOUT=90
PBP_SLEEP_SECONDS=1.2
PBP_MAX_FAILURES=12
PBP_RETRY_ATTEMPTS=3
PBP_PROVIDER=nba_api
```

CLI (lokalnie):

```bash
python3 -m nba_ovr ingest --pbp-provider nba_api --pbp-max-failures 12 --pbp-sleep 1.2 --nba-api-timeout 90 --pbp-retry-attempts 3
```

CLI (cloud / CI):

```bash
python3 -m nba_ovr ingest --pbp-provider none
```
