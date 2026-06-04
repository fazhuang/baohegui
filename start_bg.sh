#!/bin/bash
PROJECT_DIR="/Users/likeming/Sites/baohegui"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
VENV_UVICORN="$BACKEND_DIR/.venv/bin/uvicorn"
VITE_BIN="$FRONTEND_DIR/node_modules/.bin/vite"

pg_isready -q 2>/dev/null || brew services start postgresql@16 2>/dev/null
sleep 2

cd "$BACKEND_DIR"
.venv/bin/python -c "import sys; sys.path.insert(0,'.'); from app.db.database import init_db; init_db()" 2>/dev/null

pkill -f "uvicorn app.main" 2>/dev/null
sleep 1
cd "$BACKEND_DIR"
nohup $VENV_UVICORN app.main:app --host 0.0.0.0 --port 8000 > /tmp/bhg_backend.log 2>&1 &

for i in 1 2 3 4 5; do
    sleep 1
    curl -s http://127.0.0.1:8000/health > /dev/null 2>&1 && break
done

pkill -f "vite --host" 2>/dev/null
sleep 1
cd "$FRONTEND_DIR"
nohup $VITE_BIN --host 0.0.0.0 --port 3000 > /tmp/bhg_frontend.log 2>&1 &

sleep 3
open http://localhost:3000
