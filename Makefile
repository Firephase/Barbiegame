.PHONY: help up down logs install update serve dev-backend dev-frontend dev test typecheck build clean

help:
	@echo "Docker (nothing to install but Docker itself):"
	@echo "  up            Build and run on http://localhost:8000"
	@echo "  down          Stop the stack"
	@echo "  logs          Follow the logs"
	@echo ""
	@echo "Local (needs Python 3.11+ and Node 18+):"
	@echo "  install       Install backend and frontend dependencies"
	@echo "  update        git pull, reinstall deps, rebuild the UI"
	@echo "  serve         Run UI + API on one port (http://localhost:8000)"
	@echo "  dev           Run backend (:8000) and frontend (:5173) together"
	@echo "  dev-backend   Run the API only"
	@echo "  dev-frontend  Run the UI only"
	@echo "  test          Run the backend test suite"
	@echo "  typecheck     Typecheck the frontend"
	@echo "  build         Build the frontend for production"

# --- Docker ---------------------------------------------------------------
up:
	docker compose up --build -d
	@echo ""
	@echo "  Lumen is starting on   http://localhost:$${PORT:-8000}"
	@echo "  What is switched on:   http://localhost:$${PORT:-8000}/api/providers"
	@echo "  API docs:              http://localhost:$${PORT:-8000}/docs"
	@echo "  Follow the logs with:  make logs"

down:
	docker compose down

logs:
	docker compose logs -f lumen

# --- local ----------------------------------------------------------------
# Pull changes and rebuild whatever needs it. This is the counterpart to
# `docker compose up --build` for installs that cannot run Docker (Android
# under proot-distro, for one).
update:
	git pull
	.venv/bin/pip install -q -r backend/requirements.txt
	cd frontend && npm install --no-audit --no-fund --silent && npm run build
	@echo ""
	@echo "  Updated. Start it with:  make serve"

# Serves the built UI and the API on one port. Binds to localhost by default:
# the app has no authentication, so exposing it needs to be a deliberate act
# (HOST=0.0.0.0 make serve).
serve:
	cd backend && ../.venv/bin/uvicorn app.main:app \
		--host $${HOST:-127.0.0.1} --port $${PORT:-8000}

install:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r backend/requirements.txt
	.venv/bin/pip install pytest pytest-asyncio
	cd frontend && npm install

dev-backend:
	cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

dev:
	@$(MAKE) -j2 dev-backend dev-frontend

test:
	.venv/bin/python -m pytest backend/tests -q

typecheck:
	cd frontend && npx tsc --noEmit

build:
	cd frontend && npm run build

clean:
	rm -rf var frontend/dist .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
