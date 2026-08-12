# ============================================================================
# OpenML — convenience targets. Always run from the project root.
# ============================================================================
SHELL := /bin/bash
export OPENML_PROJECT_DIR := $(shell pwd)

# Ensure a .env exists (copied from the example) before any compose call
ENV_FILE := .env
$(ENV_FILE):
	@cp .env.example .env && echo "Created .env from .env.example"

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: up
up: $(ENV_FILE) ## Start CORE stack (postgres, minio, redis, dashboard)
	docker compose up -d --build
	@echo ""
	@echo "  OpenML console:  http://localhost:$${DASHBOARD_PORT:-8080}"
	@echo "  MinIO console:   http://localhost:$${MINIO_CONSOLE_PORT:-9001}"

.PHONY: down
down: ## Stop and remove ALL OpenML containers (keeps volumes/data)
	docker compose --profile "*" down

.PHONY: stop
stop: ## Stop everything but keep containers (fast restart, frees RAM)
	docker compose stop

.PHONY: develop
develop: $(ENV_FILE) ## Start the develop stack (JupyterLab)
	docker compose up -d --build jupyter
	@echo "  JupyterLab:  http://localhost:$${JUPYTER_PORT:-8888}  (token: $${JUPYTER_TOKEN:-openml})"

.PHONY: build
build: ## Build local images (dashboard + jupyter)
	docker compose build

.PHONY: ps
ps: ## Show status of all OpenML containers
	docker compose --profile "*" ps

.PHONY: logs
logs: ## Tail logs (usage: make logs S=jupyter)
	docker compose logs -f $(S)

.PHONY: config
config: $(ENV_FILE) ## Validate & render the merged compose config
	docker compose --profile "*" config

.PHONY: prune
prune: ## Reclaim disk: dangling images, stopped junk, unused build cache
	docker builder prune -f
	docker image prune -f
	docker volume prune -f
	@echo "reclaimed — run 'docker system df' to check"

.PHONY: nuke
nuke: ## DANGER: remove containers AND volumes (wipes all data)
	docker compose --profile "*" down -v
