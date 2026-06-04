import { APIRequestContext, Page, test as base } from '@playwright/test';

export const TEST_USER = {
  username: 'e2e-test-user',
  password: 'Test123456',
  company: '测试公司',
  email: 'e2e@test.com',
};

export const BACKEND_URL = 'http://backend:8000';

/**
 * 通过 API 获取认证 token（注册+登录）
 */
export async function getAuthToken(request: APIRequestContext): Promise<string> {
  // 先尝试登录
  const loginRes = await request.post(`${BACKEND_URL}/api/auth/login`, {
    data: { username: TEST_USER.username, password: TEST_USER.password },
  });
  if (loginRes.ok()) {
    return (await loginRes.json()).access_token;
  }

  // 注册
  const regRes = await request.post(`${BACKEND_URL}/api/auth/register`, {
    data: TEST_USER,
  });
  if (!regRes.ok()) {
    throw new Error(`注册失败: ${regRes.status()} ${await regRes.text()}`);
  }
  return (await regRes.json()).access_token;
}

/**
 * 通过 localStorage 注入认证信息，实现快速登录
 */
export async function loginViaApi(page: Page, request: APIRequestContext) {
  const token = await getAuthToken(request);
  await page.goto('/login');
  await page.evaluate(
    ({ t, u }) => {
      localStorage.setItem('token', t);
      localStorage.setItem('role', 'user');
      localStorage.setItem('username', u);
    },
    { t: token, u: TEST_USER.username },
  );
}

/**
 * 通过 API 上传测试文件并返回 file_id
 */
export async function uploadFileViaApi(
  request: APIRequestContext,
  token: string,
  filePath: string,
): Promise<number> {
  const fs = await import('fs');
  const fileBuffer = fs.readFileSync(filePath);

  const resp = await request.post(`${BACKEND_URL}/api/upload/`, {
    headers: { Authorization: `Bearer ${token}` },
    multipart: {
      file: {
        name: 'test_bidding_doc.docx',
        mimeType:
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        buffer: fileBuffer,
      },
    },
  });

  if (!resp.ok()) {
    throw new Error(`上传失败: ${resp.status()} ${await resp.text()}`);
  }
  return (await resp.json()).db_id;
}

/**
 * 通过 API 触发合规检查并返回 report_id
 */
export async function triggerCheck(
  request: APIRequestContext,
  token: string,
  fileId: number,
): Promise<number> {
  const resp = await request.post(`${BACKEND_URL}/api/check/${fileId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok()) {
    throw new Error(`检查失败: ${resp.status()} ${await resp.text()}`);
  }
  return (await resp.json()).report_id;
}

/**
 * 等待 Ant Design 的加载指示器消失
 */
export async function waitPageReady(page: Page) {
  await page.waitForLoadState('networkidle');
  // 等待所有 ant-spin 消失
  const spinners = page.locator('.ant-spin-spinning');
  const count = await spinners.count();
  for (let i = 0; i < count; i++) {
    if (await spinners.nth(i).isVisible({ timeout: 3000 }).catch(() => false)) {
      await spinners.nth(i).waitFor({ state: 'hidden', timeout: 20000 });
    }
  }
}

/**
 * 截图辅助：将截图保存到固定目录
 */
export async function saveScreenshot(page: Page, name: string) {
  await page.screenshot({
    path: `/app/screenshots/${name}.png`,
    fullPage: true,
  });
}
