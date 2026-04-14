VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest

.PHONY: setup configure run test clean db-stats db-vacuum

setup: $(VENV)/bin/activate

$(VENV)/bin/activate: requirements.txt requirements-dev.txt
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install -r requirements-dev.txt
	touch $(VENV)/bin/activate

configure: $(VENV)/bin/activate
	$(PYTHON) scripts/configure.py

run: $(VENV)/bin/activate
	PYTHONPATH=src $(PYTHON) -m firooz

test: $(VENV)/bin/activate
	PYTHONPATH=src $(PYTEST) tests/ -v

db-stats: $(VENV)/bin/activate
	$(PYTHON) scripts/dbstats.py

db-vacuum: $(VENV)/bin/activate
	$(PYTHON) -c "import sqlite3, os; db=os.environ.get('DB_PATH','firooz.db'); s=os.path.getsize(db); conn=sqlite3.connect(db); conn.execute('VACUUM'); conn.close(); print(f'Vacuumed: {s} → {os.path.getsize(db)} bytes')"

clean:
	rm -rf $(VENV) __pycache__ src/firooz/__pycache__ tests/__pycache__ *.db .pytest_cache
