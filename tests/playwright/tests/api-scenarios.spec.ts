import { APIRequestContext, test as base } from '@playwright/test';
import { getAuthToken, uploadFileViaApi, triggerCheck, BACKEND_URL, TEST_USER } from './helpers';
import * as fs from 'fs';

/**
 * 第 4 步补充：通过 Playwright 请求上下文执行 API 场景测试
 * 这是对 curl API 测试的 Playwright 版本（步骤 4 的补充）
 */

test.describe('API 场景测试（Playwright 版）', () => {
  let token_user: string;
  let token_admin: string;

  test.beforeAll(async ({ request }) => {
    // 获取普通用户 token
    token_user = await getAuthToken(request);

    // 管理员 — 尝试获取
    const adminLogin = await request.post(`${BACKEND_URL}/api/auth/login`, {
      data: { username: 'admin', password: 'admin123' },
    });
    if (adminLogin.ok()) {
      token_admin = (await adminLogin.json()).access_token;
    }
  });

  // 验证后端 API 可用性（替代 curl 的 Playwright 方式）
  test('API 健康检查', async ({ request }) => {
    const resp = await request.get(`${BACKEND_URL}/health`);
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data.status).toBe('ok');
  });

  test('API 注册/登录', async () => {
    expect(token_user).toBeTruthy();
  });

  test.skip('API 文件上传和合规检查', async ({ request }) => {
    // 需要测试文档存在
    const docPath = '/tmp/test_bidding_doc_e2e.docx';
    if (!fs.existsSync(docPath)) {
      test.skip();
      return;
    }

    const fileId = await uploadFileViaApi(request, token_user, docPath);
    expect(fileId).toBeGreaterThan(0);

    const reportId = await triggerCheck(request, token_user, fileId);
    expect(reportId).toBeGreaterThan(0);

    // 查看报告详情
    const reportResp = await request.get(
      `${BACKEND_URL}/api/report/${reportId}`,
      { headers: { Authorization: `Bearer ${token_user}` } },
    );
    expect(reportResp.ok()).toBeTruthy();
    const report = await reportResp.json();
    expect(report.total_score).toBeDefined();
    expect(report.total_violations).toBeDefined();
  });

  test('API 报告列表', async ({ request }) => {
    const resp = await request.get(`${BACKEND_URL}/api/report/list/`, {
      headers: { Authorization: `Bearer ${token_user}` },
    });
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(Array.isArray(data)).toBeTruthy();
  });

  test.skip('API 规则管理（管理员）', async ({ request }) => {
    if (!token_admin) {
      test.skip();
      return;
    }
    const resp = await request.get(`${BACKEND_URL}/api/rules/engine/status`, {
      headers: { Authorization: `Bearer ${token_admin}` },
    });
    expect(resp.ok()).toBeTruthy();
  });

  test('API 未认证访问应被拒绝', async ({ request }) => {
    const resp = await request.get(`${BACKEND_URL}/api/report/list/`);
    expect(resp.status()).toBe(401);
  });
});

test.describe('API 异常流程', () => {
  let token: string;

  test.beforeAll(async ({ request }) => {
    token = await getAuthToken(request);
  });

  test('不存在的文件检查应返回错误', async ({ request }) => {
    const resp = await request.post(`${BACKEND_URL}/api/check/99999`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.status()).toBeGreaterThanOrEqual(400);
  });

  test('不存在的用户登录应返回 401', async ({ request }) => {
    const resp = await request.post(`${BACKEND_URL}/api/auth/login`, {
      data: { username: 'nonexistent_user_xyz', password: 'wrong' },
    });
    expect(resp.status()).toBe(401);
  });
});
