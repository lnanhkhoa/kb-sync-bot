.DEFAULT_GOAL := help
.PHONY: help setup test scrape upload ask job docker-build docker-run

LIMIT   ?= 40
INCLUDE ?= how-to-use-youtube-with-optisigns
Q       ?= How do I add a YouTube video?
IMAGE   ?= optibot

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-13s %s\n", $$1, $$2}'

setup: ## Install deps and create .env from the sample
	uv sync
	@test -f .env || cp .env.sample .env

test: ## Run unit tests
	uv run pytest

scrape: ## Scrape INCLUDE + the most recently updated articles, LIMIT in total, into articles/
	uv run python -m optibot.scrape --limit $(LIMIT) --include $(INCLUDE)

upload: ## Sync articles/ to the File Search store, pruning articles no longer scraped
	uv run python -m optibot.upload --prune

ask: ## Ask the assistant: make ask Q="..."
	uv run python -m optibot.assistant "$(Q)"

job: ## Run the daily job once (scrape + delta upload)
	uv run python main.py

docker-build: ## Build the job image
	docker build -t $(IMAGE) .

docker-run: ## Run the job image once with .env
	docker run --rm --env-file .env $(IMAGE)
