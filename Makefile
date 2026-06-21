.PHONY: test lint test-orbit demo install coverage

install:
	pip install -e ".[dev]"

test:
	pytest tests/unit/ -v

coverage:
	pytest tests/unit/ --cov=src/rootchain --cov-report=term-missing --cov-report=html

lint:
	ruff check src/ tests/
	mypy src/rootchain/

test-orbit:
	python scripts/test_orbit_connection.py

demo:
	python scripts/generate_test_issue.py --language python
