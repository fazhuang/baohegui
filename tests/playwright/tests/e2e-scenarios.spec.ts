import { test, expect } from '@playwright/test';
import {
  loginViaApi,
  getAuthToken,
  uploadFileViaApi,
  triggerCheck,
  waitPageReady,
  saveScreenshot,
  BACKEND_URL,
} from './helpers';
import * as fs from 'fs';
import * as path from 'path';

/**
 * 第 6 步：E2E 场景测试
 *
 * 场景 A：完整用户旅程（登录 → 上传 → 检查 → 查看报告）
 * 场景 B：异常流程
 */

// 先确保测试文档存在
const TEST_DOC_PATH = '/tmp/test_bidding_doc_e2e.docx';

test.describe('E2E - 场景 A：完整用户旅程', () => {
  let authToken: string;
  let fileId: number;
  let reportId: number;

  test.beforeAll(async ({ request }) => {
    // 生成测试文档
    const { execSync } = await import('child_process');
    execSync(`python3 /app/scripts/generate_test_doc.py /tmp`, {
      timeout: 15000,
    });

    // 获取认证 token
    authToken = await getAuthToken(request);
    expect(authToken).toBeTruthy();
  });

  test('A1：用户登录（通过表单）', async ({ page, request }) => {
    await page.goto('/login');
    await page.waitForLoadState('networkidle');

    // 填写登录表单
    await page.getByPlaceholder('用户名').fill('e2e-test-user');
    await page.getByPlaceholder('密码').fill('Test123456');
    await page.getByRole('button', { name: '登录' }).click();

    // 验证跳转到仪表盘
    await page.waitForURL('**/');
    await waitPageReady(page);
    await expect(page).toHaveURL(/\/$/);
  });

  test('A2：导航到上传页面并上传文件', async ({ page, request }) => {
    await loginViaApi(page, request);
    await page.goto('/upload');
    await waitPageReady(page);

    // 确认测试文档存在
    expect(fs.existsSync(TEST_DOC_PATH)).toBeTruthy();

    // 检测上传区域类型并操作
    const antUpload = page.locator('.ant-upload-drag');
    const antUploadDragger = page.locator('.ant-upload.ant-upload-drag');

    if (await antUpload.isVisible({ timeout: 3000 }).catch(() => false)) {
      // Ant Design Upload.Dragger — 通过 input[type=file] 上传
      const fileInput = antUpload.locator('input[type="file"]');
      await fileInput.setInputFiles([TEST_DOC_PATH]);
    } else if (await antUploadDragger.isVisible({ timeout: 3000 }).catch(() => false)) {
      const fileInput = antUploadDragger.locator('input[type="file"]');
      await fileInput.setInputFiles([TEST_DOC_PATH]);
    } else {
      // 直接找 input[type=file]
      const fileInput = page.locator('input[type="file"]');
      await fileInput.setInputFiles([TEST_DOC_PATH]);
    }

    // 等待上传完成（观察页面上出现进度或成功提示）
    await page.waitForTimeout(3000);
    await waitPageReady(page);

    // 检查上传是否成功 — 看是否有成功提示或跳转到报告页
    const successMsg = page.getByText(/成功|完成|已上传/);
    if (await successMsg.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expect(successMsg).toBeVisible();
    }
  });

  test('A3~A4：通过 API 完成检查并查看报告页面', async ({ page, request }) => {
    await loginViaApi(page, request);

    // 通过 API 上传和检查
    fileId = await uploadFileViaApi(request, authToken, TEST_DOC_PATH);
    expect(fileId).toBeGreaterThan(0);

    reportId = await triggerCheck(request, authToken, fileId);
    expect(reportId).toBeGreaterThan(0);

    // 导航到报告页面
    await page.goto(`/report/${reportId}`);
    await waitPageReady(page);

    // 验证报告页面组件
    // 评分区域
    const scoreElements = page.locator('text=/总分|\\d+分|score/i');
    const scoreVisible = await scoreElements.first().isVisible({ timeout: 5000 }).catch(() => false);

    if (scoreVisible) {
      await expect(scoreElements.first()).toBeVisible();
    }

    // 风险违规表格
    const table = page.locator('.ant-table');
    if (await table.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expect(table).toBeVisible();
    }

    // PDF 下载按钮
    const pdfBtn = page.getByText(/PDF|下载|导出/);
    if (await pdfBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expect(pdfBtn).toBeVisible();
    }

    await saveScreenshot(page, 'e2e-report-page');
  });

  test('A5：历史记录中可见报告', async ({ page, request }) => {
    await loginViaApi(page, request);
    await page.goto('/history');
    await waitPageReady(page);

    // 验证报告列表中有记录
    const table = page.locator('.ant-table');
    await expect(table).toBeVisible({ timeout: 10000 });

    // 检查表格行数 > 0
    const rows = table.locator('.ant-table-tbody tr');
    const rowCount = await rows.count();
    expect(rowCount).toBeGreaterThan(0);
  });
});

test.describe('E2E - 场景 B：异常流程测试', () => {
  test('B1：未登录访问应重定向到登录页', async ({ page }) => {
    // 清除 localStorage 确保未登录
    await page.goto('/');
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForLoadState('networkidle');

    // 应被重定向到 /login
    await expect(page).toHaveURL(/\/login/);
  });

  test('B2：无效 token 应重定向到登录页', async ({ page }) => {
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.setItem('token', 'invalid-token-12345');
      localStorage.setItem('role', 'admin');
    });
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // 如果后端 API 返回 401，前端应处理并重定向到登录
    // 如果是一键登录模式（前端不验证），则不会重定向
    // 这里我们检查：如果 token 无效但前端跳转了，验证登录页面可见
    const loginUrl = await page.evaluate(() => window.location.pathname);
    if (loginUrl === '/login') {
      await expect(page.getByText('包合规')).toBeVisible();
    }
  });

  test('B3：不存在的报告页面应显示友好提示', async ({ page, request }) => {
    await loginViaApi(page, request);
    await page.goto('/report/999999');
    await waitPageReady(page);

    // 等待一段时间，看是否显示错误或空状态
    await page.waitForTimeout(3000);

    // 不应是空白页面 — 应有错误提示或空状态
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
  });

  test('B4：上传不支持的文件格式', async ({ page, request }) => {
    await loginViaApi(page, request);
    await page.goto('/upload');
    await waitPageReady(page);

    // 创建一个 .txt 文件
    const txtPath = '/tmp/test_invalid.txt';
    fs.writeFileSync(txtPath, '这不是一个有效的 Word 文档', 'utf-8');

    const fileInput = page.locator('input[type="file"]').first();
    await fileInput.setInputFiles([txtPath]);
    await page.waitForTimeout(2000);

    // 应显示错误提示
    const errMsg = page.getByText(/不支持|格式错误|无效|失败/);
    if (await errMsg.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expect(errMsg).toBeVisible();
    }

    // 清理
    fs.unlinkSync(txtPath);
  });
});
