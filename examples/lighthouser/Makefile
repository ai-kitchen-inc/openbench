.PHONY: server frontend install dev clean test

# ── Quick start ──

dev: ## Run server + frontend concurrently
	@$(MAKE) -j2 server frontend

server: ## Start FastAPI backend (port 8001)
	uvicorn server:app --port 8001 --reload

frontend: ## Start Vite dev server (port 5173, proxies to 8001)
	cd frontend && pnpm dev

# ── Setup ──

install: ## Install all dependencies
	pip install -e "../../.[chat]"
	cd frontend && pnpm install

# ── Utilities ──

test: ## Run semap_engine standalone tests
	python semap_engine.py

clean: ## Remove generated files
	rm -rf uploads/ lighthouser_memory.db frontend/node_modules frontend/dist __pycache__

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
