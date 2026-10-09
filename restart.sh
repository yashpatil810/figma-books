#!/bin/zsh
# Stops any running Book Builder, rebuilds the web UI, and starts it again on http://localhost:8765
cd "$(dirname "$0")"
PORT=8765

echo "• Stopping the old copy (if any)…"
pkill -f "uvicorn app.main" 2>/dev/null
lsof -ti tcp:$PORT 2>/dev/null | xargs kill 2>/dev/null
sleep 1

[ -d .venv ] || { echo "• First run: creating Python environment…"; python3 -m venv .venv && .venv/bin/pip install -q fastapi "uvicorn[standard]" python-docx lxml httpx pyspellchecker pydantic pillow pypdf; }
.venv/bin/pip install -q -r /dev/null 2>/dev/null
.venv/bin/pip install -q pypdf pillow 2>/dev/null

echo "• Rebuilding the web UI…"
(cd frontend && { [ -d node_modules ] || npm install --no-audit --no-fund; } && npm run build) || { echo "UI build failed"; exit 1; }

echo "• Starting on http://localhost:$PORT  (Ctrl+C to stop)"
open "http://localhost:$PORT" 2>/dev/null &
exec .venv/bin/uvicorn app.main:app --app-dir backend --port $PORT
