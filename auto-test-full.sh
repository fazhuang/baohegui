#!/bin/bash
# 完整自动化部署与测试 - Playwright 集成版
# 执行全部 7 步流程
set -euo pipefail

cd "$(dirname "$0")"

echo "═══════════════════════════════════════"
echo "  包合规 - 自动化部署与测试"
echo "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════"

PASS=0
FAIL=0
fail() { echo "❌ $1"; FAIL=$((FAIL + 1)); }
pass() { echo "✅ $1"; PASS=$((PASS + 1)); }

# ============================================
# 第 1 步：Docker 构建部署
# ============================================
echo ""
echo "══════ 第 1 步：Docker 构建部署 ══════"
docker compose down -v --remove-orphans 2>/dev/null || true
docker compose up -d --build 2>&1 || { fail "Docker 构建部署失败"; exit 1; }

echo "等待服务就绪..."
for i in $(seq 1 30); do
  backend_ok=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null) || backend_ok="000"
  frontend_ok=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/ 2>/dev/null) || frontend_ok="000"
  if [ "$backend_ok" = "200" ] && [ "$frontend_ok" = "200" ]; then
    echo "✅ 所有服务就绪（第 ${i}s）"
    break
  fi
  if [ $i -eq 30 ]; then
    fail "服务启动超时（后端=$backend_ok 前端=$frontend_ok）"
  fi
  sleep 2
done
pass "Docker 部署完成"

# ============================================
# 第 2 步：API 冒烟测试
# ============================================
echo ""
echo "══════ 第 2 步：API 冒烟测试 ══════"
BASE="http://localhost:8000"

# 健康检查
curl -s "$BASE/health" | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert d['status']=='ok'" 2>/dev/null && pass "健康检查" || fail "健康检查"

# 注册测试用户
curl -s -X POST "$BASE/api/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"username":"autotest","password":"test123","company":"测试公司","email":"autotest@test.com"}' | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert 'access_token' in d" 2>/dev/null && pass "用户注册" || echo "  ⚠️ 可能已存在（忽略）"

# 登录
TOKEN=$(curl -s -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"autotest","password":"test123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null) && pass "用户登录" || fail "用户登录"

# 用户信息
curl -s "$BASE/api/auth/me" -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json; d=json.load(sys.stdin)
assert d['username'] == 'autotest'" 2>/dev/null && pass "用户信息" || fail "用户信息"

# ============================================
# 第 3 步：pytest
# ============================================
echo ""
echo "══════ 第 3 步：pytest ══════"
docker compose exec -T backend python -m pytest tests/ -v --tb=short 2>&1 | tail -20
if [ ${PIPESTATUS[0]} -eq 0 ]; then
  pass "pytest"
else
  fail "pytest"
fi

# ============================================
# 第 4 步：API 场景测试（Playwright 版）
# ============================================
echo ""
echo "══════ 第 4 步：API 场景测试 ══════"
docker compose run --rm --profile test playwright npx playwright test --grep "API" 2>&1 | tail -20
if [ ${PIPESTATUS[0]} -eq 0 ]; then
  pass "API 场景测试"
else
  fail "API 场景测试"
fi

# ============================================
# 第 5 步：浏览器 UI 测试（Playwright）
# ============================================
echo ""
echo "══════ 第 5 步：浏览器 UI 测试 ══════"
docker compose run --rm --profile test playwright npx playwright test --grep "UI" 2>&1 | tail -20
if [ ${PIPESTATUS[0]} -eq 0 ]; then
  pass "浏览器 UI 测试"
else
  fail "浏览器 UI 测试"
fi

# ============================================
# 第 6 步：E2E 场景测试（Playwright）
# ============================================
echo ""
echo "══════ 第 6 步：E2E 场景测试 ══════"
docker compose run --rm --profile test playwright npx playwright test --grep "E2E" 2>&1 | tail -20
if [ ${PIPESTATUS[0]} -eq 0 ]; then
  pass "E2E 场景测试"
else
  fail "E2E 场景测试"
fi

# ============================================
# 第 7 步：汇总
# ============================================
echo ""
echo "═══════════════════════════════════════"
echo "  自动化测试报告"
echo "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "  通过: $PASS  失败: $FAIL"
echo "═══════════════════════════════════════"

if [ $FAIL -gt 0 ]; then
  exit 1
fi
