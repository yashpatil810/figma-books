#!/bin/zsh
# Starts Book Builder on http://localhost:8765 (backend + built UI).
cd "$(dirname "$0")"
lsof -ti tcp:8765 2>/dev/null | xargs kill 2>/dev/null; sleep 1
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q fastapi "uvicorn[standard]" python-docx lxml httpx pyspellchecker pydantic pillow openpyxl; }
[ -d frontend/dist ] || (cd frontend && npm install --no-audit --no-fund && npm run build)
open http://localhost:8765 2>/dev/null &
exec .venv/bin/uvicorn app.main:app --app-dir backend --port 8765
