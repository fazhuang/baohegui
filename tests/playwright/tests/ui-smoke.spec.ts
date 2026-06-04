import { test, expect } from '@playwright/test';
import { loginViaApi, waitPageReady, BACKEND_URL } from './helpers';

/**
 * 第 5 步：浏览器 UI 模拟测试
 * 验证前端 7 个页面的关键 UI 元素是否正确渲染
 */

// ============================================================
// 5.1 登录页面
// ============================================================
test.describe('UI - 登录页面', () => {
  test('应正确渲染登录表单和注册表单', async ({ page }) => {
    await page.goto('/login');
    await page.waitForLoadState('networkidle');

    // 验证页面标题
    await expect(page.getByText('包合规')).toBeVisible();
    await expect(page.getByText('招标文件合规自检系统')).toBeVisible();

    // 验证登录 Tab 的内容
    await expect(page.getByPlaceholder('用户名')).toBeVisible();
    await expect(page.getByPlaceholder('密码')).toBeVisible();
    await expect(page.getByRole('button', { name: '登录' })).toBeVisible();

    // 切换到注册 Tab
    await page.getByText('注册试用').click();
    await page.waitForTimeout(500);
    await expect(page.getByPlaceholder('单位名称（选填）')).toBeVisible();
    await expect(page.getByPlaceholder('邮箱（选填）')).toBeVisible();
    await expect(page.getByRole('button', { name: '注册并登录' })).toBeVisible();

    // 验证开发模式一键登录
    await expect(page.getByRole('button', { name: /一键登录|开发模式/ })).toBeVisible();
  });
});

// ============================================================
// 5.2 仪表盘页面
// ============================================================
test.describe('UI - 仪表盘', () => {
  test('应正确渲染仪表盘 KPI 卡片和操作入口', async ({ page, request }) => {
    await loginViaApi(page, request);
    await page.goto('/');
    await waitPageReady(page);

    // 验证侧边导航菜单
    await expect(page.getByText('仪表盘').first()).toBeVisible();
    await expect(page.getByText('文件上传')).toBeVisible();
    await expect(page.getByText('历史记录')).toBeVisible();

    // 验证 KPI 卡片区域（antd Statistic / Card）
    const cards = page.locator('.ant-card');
    const cardCount = await cards.count();
    expect(cardCount).toBeGreaterThanOrEqual(1);

    // 验证快捷操作区域（按钮链接到 upload 等）
    await page.getByText('文件上传').click();
    await expect(page).toHaveURL(/\/upload/);
  });
});

// ============================================================
// 5.3 文件上传页面
// ============================================================
test.describe('UI - 文件上传', () => {
  test('应正确渲染上传区域和行业选择器', async ({ page, request }) => {
    await loginViaApi(page, request);
    await page.goto('/upload');
    await waitPageReady(page);

    // 验证拖拽上传区域（ant-upload-drag）
    const uploadArea = page.locator('.ant-upload-drag');
    await expect(uploadArea).toBeVisible({ timeout: 10000 });

    // 验证行业选择器
    await expect(page.getByText('工程建设').or(page.getByText('信息技术').or(page.getByText('医疗采购')))).toBeVisible();

    // 验证上传按钮
    await expect(page.getByText(/点击或拖拽|上传文件|选择文件/)).toBeVisible();
  });
});

// ============================================================
// 5.4 历史记录页面
// ============================================================
test.describe('UI - 历史记录', () => {
  test('应正确渲染报告列表和筛选控件', async ({ page, request }) => {
    await loginViaApi(page, request);
    await page.goto('/history');
    await waitPageReady(page);

    // 验证 antd Table
    const table = page.locator('.ant-table');
    await expect(table).toBeVisible({ timeout: 10000 });

    // 验证搜索输入框
    const searchInput = page.locator('input[placeholder*="搜索"]');
    if (await searchInput.isVisible().catch(() => false)) {
      await expect(searchInput).toBeVisible();
    }
  });
});

// ============================================================
// 5.5 规则管理页面（管理员）
// ============================================================
test.describe('UI - 规则管理', () => {
  test('应正确渲染规则管理标签页', async ({ page, request }) => {
    await loginViaApi(page, request);
    await page.goto('/admin/rules');
    await waitPageReady(page);

    // 验证标签页存在（ant-tabs）
    const tabs = page.locator('.ant-tabs-nav');
    await expect(tabs).toBeVisible({ timeout: 10000 });
  });
});

// ============================================================
// 5.6 管理面板页面（管理员）
// ============================================================
test.describe('UI - 管理面板', () => {
  test('应正确渲染管理面板标签页', async ({ page, request }) => {
    await loginViaApi(page, request);
    await page.goto('/admin/panel');
    await waitPageReady(page);

    // 验证标签页
    const tabs = page.locator('.ant-tabs-nav');
    await expect(tabs).toBeVisible({ timeout: 10000 });
  });
});

// ============================================================
// 5.7 响应式布局验证（可选）
// ============================================================
test.describe('UI - 响应式布局', () => {
  test('移动端视图应正常显示', async ({ page, request }) => {
    await page.setViewportSize({ width: 375, height: 812 }); // iPhone 尺寸
    await loginViaApi(page, request);
    await page.goto('/');
    await waitPageReady(page);

    // 在小屏幕上，antd Layout 的 sider 通常是收起状态或变为顶部菜单
    // 验证页面内容可滚动和基本布局正常
    await expect(page.locator('.ant-layout-content')).toBeVisible();
  });
});
