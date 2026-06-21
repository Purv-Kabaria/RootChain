.PHONY: test lint test-orbit demo demo-dry-run validate install coverage

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

validate:
	python scripts/validate_flow.py

demo:
	python scripts/generate_test_issue.py --language python

demo-dry-run:
	@echo "Preview what RootChain would comment on issue #$(ISSUE_IID)"
	python -m src.rootchain.orchestrator \
		--project-path "$(PROJECT_PATH)" \
		--issue-iid "$(ISSUE_IID)" \
		--dry-run
