#!/bin/bash
# ==========================================
# 包合规 (baohegui) - 一键启动脚本
# 使用方式: bash /Users/likeming/Sites/baohegui/start.sh
# ==========================================

PROJECT_DIR="/Users/likeming/Sites/baohegui"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"
VENV_UVICORN="$BACKEND_DIR/.venv/bin/uvicorn"
VITE_BIN="$FRONTEND_DIR/node_modules/.bin/vite"

echo ""
echo "📋 包合规 - 启动服务"
echo "========================================"

# 1. PostgreSQL
echo "1️⃣  检查 PostgreSQL..."
pg_isready -q 2>/dev/null
if [ $? -ne 0 ]; then
    brew services start postgresql@16 2>/dev/null
    sleep 3
fi
pg_isready -q 2>/dev/null && echo "    ✅ PostgreSQL 已就绪" || echo "    ❌ PostgreSQL 启动失败"

# 2. 数据库表初始化
echo "2️⃣  初始化数据库..."
$VENV_PYTHON -c "
import sys; sys.path.insert(0, ".")
from app.db.database import init_db
init_db()
from sqlalchemy import create_engine, inspect
engine = create_engine('postgresql://baohegui:baohegui@localhost:5432/baohegui')
tables = inspect(engine).get_table_names()
print(f'    表 ({len(tables)}): {\" \".join(tables)}')
" 2>/dev/null
echo "    ✅ 数据库已就绪"

# 3. 启动后端
echo "3️⃣  启动后端 (8000)..."
pkill -f "uvicorn app.main" 2>/dev/null
sleep 1
cd $BACKEND_DIR && nohup $VENV_UVICORN app.main:app --host 0.0.0.0 --port 8000 > /tmp/bhg_backend.log 2>&1 &
BACKEND_PID=$!
sleep 3

curl -s http://127.0.0.1:8000/health > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "    ✅ 后端已启动 (PID: $BACKEND_PID)"
else
    echo "    ❌ 后端启动失败，日志:"
    tail -5 /tmp/bhg_backend.log
fi

# 4. 启动前端
echo "4️⃣  启动前端 (3000)..."
pkill -f "vite --host" 2>/dev/null
sleep 1
cd $FRONTEND_DIR && nohup $VITE_BIN --host 0.0.0.0 --port 3000 > /tmp/bhg_frontend.log 2>&1 &
FRONTEND_PID=$!
sleep 4

curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/ 2>/dev/null | grep -q 200
if [ $? -eq 0 ]; then
    echo "    ✅ 前端已启动 (PID: $FRONTEND_PID)"
else
    echo "    ⚠️  前端启动状态未知，请检查 /tmp/bhg_frontend.log"
fi

# 5. 输出结果
echo ""
echo "========================================"
echo "  ✅ 包合规服务已全部启动"
echo "  📍 前端: http://localhost:3000"
echo "  📍 后端: http://localhost:8000"
echo "  📍 API:  http://localhost:8000/docs"
echo ""
echo "  🔑 登录方式（任选其一）:"
echo "     1. 点击「开发模式 - 一键登录」"
echo "     2. admin / admin123 (管理员)"
echo "     3. user  / user123  (测试用户)"
echo ""
echo "  🛑 停止服务: pkill -f 'uvicorn app.main' && pkill -f vite"
echo "  📋 查看日志: tail -f /tmp/bhg_backend.log"
echo "========================================"
