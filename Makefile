.PHONY: help build publish publish-test lint format test clean install dev

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

build: clean ## Build wheel and sdist
	python -m build

publish: build ## Build and upload to PyPI
	. ./set_creds.sh && twine upload dist/*

publish-test: build ## Build and upload to TestPyPI
	. ./set_creds.sh && twine upload --repository testpypi dist/*

lint: ## Run ruff check
	ruff check .

format: ## Run ruff format
	ruff format .

test: ## Run pytest
	pytest -q

clean: ## Remove build artifacts
	rm -rf dist/ build/ src/*.egg-info

install: ## Install in development mode
	pip install -e .

dev: ## Install with dev dependencies
	pip install -e ".[dev]"
