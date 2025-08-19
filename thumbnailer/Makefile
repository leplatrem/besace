INSTALL_STAMP_PYTHON := .install.python.stamp
INSTALL_STAMP_NODE := .install.node.stamp
ENV_FILE := .env
UV := $(shell command -v uv 2> /dev/null)
SOURCES := thumbnailer.py

.PHONY: help clean lint format migrate demo tests browser-tests

help:
	@echo "Please use 'make <target>' where <target> is one of the following commands.\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' Makefile | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'
	@echo "\nCheck the Makefile to know exactly what each target is doing."

clean:  ## Delete cache files
	find . -type d -name "__pycache__" | xargs rm -rf {};
	rm -rf $(INSTALL_STAMP_PYTHON) .coverage .*_cache .venv

lint:  ## Analyze code base
	$(UV) run ruff check $(SOURCES)
	$(UV) run ruff format --check $(SOURCES)

format:  ## Format code base
	$(UV) run ruff check --fix $(SOURCES)
	$(UV) run ruff format $(SOURCES)

test: tests  ## Run unit tests
tests:
	$(UV) run pytest --cov-report term-missing --cov $(SOURCES)
