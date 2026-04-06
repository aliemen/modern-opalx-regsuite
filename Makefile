.PHONY: build-frontend install dev help

help:
	@echo "Targets:"
	@echo "  build-frontend  Build the React frontend into modern_opalx_regsuite/static/"
	@echo "  install         Install the Python package (editable) with all dependencies"
	@echo "  dev             Run the FastAPI dev server (requires config.toml)"

build-frontend:
	cd frontend && npm ci && npm run build

install: build-frontend
	pip install -e .

dev:
	opalx-regsuite serve --host 127.0.0.1 --port 8000
