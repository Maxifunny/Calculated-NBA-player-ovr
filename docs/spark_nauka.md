# Spark — ściąga na Etap 2

Cel: po jednym odpaleniu `python -m nba_ovr spark` rozumiesz, *co* Spark zrobił z Twoimi CSV.

Plik z kodem: `src/nba_ovr/spark/etl.py`.

## 1. SparkSession to nie „baza”

```python
SparkSession.builder.master("local[*]").getOrCreate()
```

`local[*]` = jeden proces JVM na Twoim laptopie, tyle wątków ile rdzeni. Nie potrzebujesz klastra, żeby nauczyć się API. Klaster zmienia się głównie w `master` i pamięci, nie w `filter` / `groupBy`.

## 2. Transformacja vs akcja

| Transformacja (leniwa) | Akcja (liczy) |
| --- | --- |
| `filter`, `select`, `join`, `groupBy().agg` | `count`, `show`, `write`, `collect` |

W ETL-u pierwszy `count()` po wczytaniu CSV to moment, w którym Spark naprawdę czyta dysk. Dlatego log `Filtr rotacji: N → M` pojawia się dopiero wtedy.

Ćwiczenie: zakomentuj oba `count()` i zostaw samo `write`. Pipeline dalej działa — Spark zwinie filtr z zapisem w jeden plan.

## 3. Dlaczego Parquet, skoro mamy CSV?

CSV jest wygodny do `less` i do Etapu 3. Parquet jest kolumnowy: `SELECT player_name, per` nie czyta kolumny play-by-play. Na sezonie NBA różnica jest kosmetyczna. Na pełnym PBP (miliony eventów) jest po to, żeby Spark w ogóle miał sens.

## 4. Play-by-play → jedna linia na gracza

Jeśli `raw_data/pbp/*.json` jest puste, ten krok jest no-op. To OK.

Gdy pliki są:

1. Spark czyta wiele JSON-ów naraz (`spark.read.json([...])`).
2. Każdy event ma do trzech `PLAYER*_ID` (aktor, odbiorca, blocker).
3. `groupBy(player_id).count()` na stealach / blockach / zbiórkach defensywnych.
4. `def_events_per_100` = te eventy / grube oszacowanie posiadania × 100.

To nie jest Tracking Data (Second Spectrum). Świadomie proste, żeby dało się to obronić na code review.

## 5. Join 2K: driver vs executory

Fuzzy matching nazw (`rapidfuzz`) jest Pythonowy i drogi. Robimy go na **driverze** na ~500–700 kartach, potem `broadcast` małej tabeli i `join` po `player_id`.

Wzór: *mały, brzydki problem w Pythonie → mapa; duży problem w Spark SQL*.

## 6. Window function

```python
Window.orderBy(col("per")).percent_rank()
```

Percentyl PER w sezonie. Window nie zmniejsza liczby wierszy (to nie jest `groupBy`). Przydaje się, gdy chcesz „ile % ligi jest gorszych od X” bez redukcji do jednej linii.

## 7. Rzeczy, których NIE rób na dużych danych

- `coalesce(1)` przed zapisem CSV — u nas celowo, bo wynik jest mały. Na terabajtach zrobisz jeden gigantyczny bottleneck.
- `toPandas()` na pełnym PBP — zbierze wszystko na driver i padnie RAM. Używamy `toPandas()` tylko na liście zawodników i kartach 2K.
- 200 partycji shuffle (default Sparka) na 400 wierszach — stąd `spark.sql.shuffle.partitions = 8`.

## 8. Mini-eksperymenty (rób je Ty)

1. Zmień `MIN_GAMES` z 15 na 40. Ile zostaje MVP-kandydatów vs role players?
2. Odfiltruj tylko `Pos == 'PG'` przed joinem 2K. Czy 2K bardziej zawyża rozgrywających?
3. Gdy już masz PBP z domu: porównaj `def_events_per_100` z `dbpm`. Czy korelują?

Po eksperymencie odpalasz tylko Etap 2 i dalej, ingest zostawiasz w spokoju.
