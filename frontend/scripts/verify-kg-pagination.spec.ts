/**
 * KG 前端分页 Network 验证脚本 (Playwright)
 *
 * 用法:
 *   1. 启动前端 dev server: npm run dev  (默认 http://localhost:5173)
 *   2. 运行: npx playwright test scripts/verify-kg-pagination.spec.ts
 *
 * 验证逻辑:
 *   1. 拦截所有 /api/* 请求，mock 返回完整用户 session + 120 条 KG 数据
 *   2. 预设 localStorage token，使 ProtectedShell 允许访问
 *   3. 打开 /kg 页面，等待渲染
 *   4. 捕获第一次 /api/kg/search 的 offset 参数 → 应为 0
 *   5. 点击分页器第 2 页按钮
 *   6. 捕获第二次 /api/kg/search 的 offset 参数 → 应为 50
 */

import { test, expect } from '@playwright/test';

const BASE_URL = 'http://localhost:5173';

test('KG pagination sends correct offset in network request', async ({ page }) => {
  const searchCaptures: Array<{ offset: number | null; limit: number | null }> = [];

  // ── Intercept ALL /api/* calls ─────────────────────
  await page.route('**/api/**', async (route) => {
    const reqUrl = route.request().url();
    const urlObj = new URL(reqUrl);

    if (urlObj.pathname === '/api/auth/me') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user_id: 1, username: 'admin', role: 'admin',
          company: 'TestCo', email: 'admin@test.com', permissions: [],
        }),
      });
    }

    if (urlObj.pathname === '/api/kg/search') {
      const offset = parseInt(urlObj.searchParams.get('offset') || '0', 10);
      const limit = parseInt(urlObj.searchParams.get('limit') || '50', 10);
      searchCaptures.push({ offset, limit });

      const total = 120;
      const end = Math.min(offset + limit, total);
      const results: Record<string, unknown>[] = [];
      for (let i = offset; i < end; i++) {
        results.push({
          id: i + 1, node_type: 'regulation',
          title: `Test Reg #${String(i + 1).padStart(4, '0')}`,
          content: `Content ${i + 1}`, source: 'Test',
          tags: 'test', trust_level: 0.8, audit_status: 'verified',
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ query: '', results, total, limit, offset }),
      });
    }

    if (urlObj.pathname === '/api/kg/stats') {
      return route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          total_nodes: 120,
          by_type: { regulation: 100, case: 10, rule: 10 },
          by_audit_status: { verified: 120 },
          total_edges: 0,
        }),
      });
    }

    if (urlObj.pathname === '/api/kg/nodes/needing-review') {
      return route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ nodes: [] }),
      });
    }

    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });

  // ── Pre-set token so ProtectedShell doesn't redirect to /login ──
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    localStorage.setItem('token', 'mock-test-token-for-pagination-verification');
  });

  // ── Navigate to /kg ─────────────────────────────────
  await page.goto(`${BASE_URL}/kg`, { waitUntil: 'networkidle', timeout: 15000 });

  // Wait for React + search to fire
  await page.waitForTimeout(3000);

  // ── Assertions ─────────────────────────────────────
  expect(searchCaptures.length, 'Expected at least 1 search request').toBeGreaterThanOrEqual(1);

  const first = searchCaptures[0];
  console.log(`[CAPTURE] Request #1: offset=${first.offset} limit=${first.limit}`);

  // ── Click page 2 ───────────────────────────────────
  const page2 = page.locator('.ant-pagination-item-2');
  if (!(await page2.isVisible({ timeout: 2000 }).catch(() => false))) {
    // Debug: dump the page structure
    console.log('Pagination element not found. Page title:', await page.title());
    const bodyText = await page.textContent('body');
    console.log('Body text (first 2000 chars):', (bodyText || '').slice(0, 2000));
  }
  await page2.click();
  await page.waitForTimeout(2000);

  expect(searchCaptures.length, 'Expected at least 2 requests after clicking page 2')
    .toBeGreaterThanOrEqual(2);

  const second = searchCaptures[searchCaptures.length - 1];
  console.log(`[CAPTURE] Request #2 (latest): offset=${second.offset} limit=${second.limit}`);

  // ── Final verification ─────────────────────────────
  const result = {
    kg_pagination_network_verified: first.offset === 0 && second.offset === 50,
    first_offset: String(first.offset ?? 'null'),
    second_offset: String(second.offset ?? 'null'),
  };
  console.log(JSON.stringify(result, null, 2));

  expect(first.offset, 'First request offset must be 0').toBe(0);
  expect(second.offset, 'Second request offset must be 50').toBe(50);
});
