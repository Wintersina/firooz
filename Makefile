VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest

.PHONY: help setup configure run test clean db-stats db-vacuum import-poems check-ollama check-config

.DEFAULT_GOAL := help

help:
	@echo "Firooz — Makefile targets:"
	@echo "  make             → show this help (default)"
	@echo "  make run         → start the bot (ensures venv, config, Ollama models)"
	@echo "  make setup       → create venv and install dependencies"
	@echo "  make configure   → set the Discord bot token (interactive)"
	@echo "  make test        → run the test suite"
	@echo "  make db-stats    → print database stats"
	@echo "  make db-vacuum   → vacuum the SQLite database"
	@echo "  make import-poems→ import Persian poems from /tmp/poems.tsv"
	@echo "  make clean       → remove venv, caches, and *.db files"

setup: $(VENV)/bin/activate

$(VENV)/bin/activate: requirements.txt requirements-dev.txt
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install -r requirements-dev.txt
	touch $(VENV)/bin/activate

configure: $(VENV)/bin/activate
	$(PYTHON) scripts/configure.py

check-ollama:
	@echo "Checking Ollama is running..."
	@curl -sf http://127.0.0.1:11434/ > /dev/null 2>&1 || \
		(echo "Starting Ollama..."; ollama serve > /dev/null 2>&1 & sleep 2)
	@echo "Ensuring qwen2.5:7b (text) is available..."
	@ollama pull qwen2.5:7b
	@echo "Ensuring qwen2.5vl:7b (vision) is available..."
	@ollama pull qwen2.5vl:7b
	@echo "Ollama ready."

check-config:
	@if [ ! -f firooz.db ]; then \
		echo "ERROR: firooz.db not found. Run 'make configure' first."; \
		exit 1; \
	fi
	@token=$$(sqlite3 firooz.db "SELECT value FROM config WHERE key='discord_bot_token'" 2>/dev/null); \
	if [ -z "$$token" ]; then \
		echo "ERROR: Discord bot token not set. Run 'make configure'."; \
		exit 1; \
	fi; \
	echo "Config OK."

run: $(VENV)/bin/activate check-config check-ollama
	PYTHONPATH=src $(PYTHON) -m firooz

test: $(VENV)/bin/activate
	PYTHONPATH=src $(PYTEST) tests/ -v

db-stats: $(VENV)/bin/activate
	$(PYTHON) scripts/dbstats.py

db-vacuum: $(VENV)/bin/activate
	$(PYTHON) -c "import sqlite3, os; db=os.environ.get('DB_PATH','firooz.db'); s=os.path.getsize(db); conn=sqlite3.connect(db); conn.execute('VACUUM'); conn.close(); print(f'Vacuumed: {s} → {os.path.getsize(db)} bytes')"

import-poems: $(VENV)/bin/activate
	PYTHONPATH=src $(PYTHON) scripts/import_poems.py

clean:
	rm -rf $(VENV) __pycache__ src/firooz/__pycache__ tests/__pycache__ *.db .pytest_cache
