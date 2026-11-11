.PHONY: dev test lint simulate
dev:
	python -m farol.api
test:
	python -m pytest
lint:
	python -m ruff check .
simulate:
	python -m farol.simulator

