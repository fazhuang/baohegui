#!/bin/bash
# Playwright 测试运行脚本
# 用法:
#   ./run-playwright.sh            # 运行所有 Playwright 测试
#   ./run-playwright.sh ui         # 仅运行 UI 冒烟测试
#   ./run-playwright.sh e2e        # 仅运行 E2E 测试
#   ./run-playwright.sh api        # 仅运行 API 测试
#   ./run-playwright.sh headed     # 有头模式（显示浏览器窗口）

set -euo pipefail

cd "$(dirname "$0")/.."

TEST_FILTER=""

case "${1:-all}" in
  ui)
    TEST_FILTER="ui-smoke"
    echo "▶ 运行 UI 冒烟测试..."
    ;;
  e2e)
    TEST_FILTER="e2e-scenarios"
    echo "▶ 运行 E2E 场景测试..."
    ;;
  api)
    TEST_FILTER="api-scenarios"
    echo "▶ 运行 API 场景测试..."
    ;;
  headed)
    echo "▶ 运行所有测试（有头模式）..."
    docker compose run --rm --profile test \
      -e PW_HEADED=1 \
      playwright npx playwright test --headed "$@"
    exit $?
    ;;
  all)
    echo "▶ 运行所有 Playwright 测试..."
    ;;
  *)
    echo "用法: $0 [ui|e2e|api|headed]"
    exit 1
    ;;
esac

if [ -n "$TEST_FILTER" ]; then
  docker compose run --rm --profile test \
    playwright npx playwright test --grep "$TEST_FILTER"
else
  docker compose run --rm --profile test \
    playwright npx playwright test
fi

echo "✅ Playwright 测试完成"
echo "查看报告: docker compose run --rm --profile test playwright npx playwright show-report"
