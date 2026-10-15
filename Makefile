# Sharma Cafe WhatsApp AI Agent — aasan commands
# `make help` chalao
.DEFAULT_GOAL := help
PY ?= python3

help: ## Ye list dikhao
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Virtual env + dependencies
	$(PY) -m venv .venv && ./.venv/bin/pip install -r requirements.txt

env: ## .env banao (.env.example se)
	cp -n .env.example .env || true
	@echo "Ab .env me apni keys daalo (WhatsApp / AI / Razorpay)"

run: ## Agent + dashboard chalao (http://localhost:8000)
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

demo: ## Terminal me poora chat demo
	$(PY) -m scripts.demo_chat --reset

migrate: ## Database schema migrations (Alembic) — production me isi se schema banega
	$(PY) -m alembic upgrade head

seed: ## Demo data (1 mahine ka hisaab) load karo
	$(PY) -m app.seed

test: ## Saare tests
	$(PY) -m pytest -q

docker: ## Docker Compose se chalao (Postgres ke saath)
	docker compose up -d --build

logs: ## Docker logs
	docker compose logs -f app

down: ## Docker band karo
	docker compose down

reset: ## Demo data reset (DB saaf karke naya demo)
	rm -rf data/*.db
	$(PY) -m app.seed

.PHONY: help install env run demo migrate seed test docker logs down reset
