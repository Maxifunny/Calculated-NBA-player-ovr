.PHONY: install ingest spark sql ovr insights all test

export PYTHONPATH := src

install:
	python3 -m pip install -e ".[dev]"

ingest:
	python3 -m nba_ovr ingest --skip-pbp

spark:
	python3 -m nba_ovr spark

sql:
	python3 -m nba_ovr sql

ovr:
	python3 -m nba_ovr ovr

insights:
	python3 -m nba_ovr insights

all:
	python3 -m nba_ovr all --skip-pbp

test:
	python3 -m pytest -q
