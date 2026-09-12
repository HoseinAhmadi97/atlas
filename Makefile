.PHONY: run test bootstrap-db lint

run:
	python -m atlas.runner

test:
	pytest

bootstrap-db:
	python scripts/bootstrap_db.py

lint:
	python -m py_compile atlas/*.py atlas/**/*.py scripts/*.py
