/**
 * App Routing RBAC Tests — 真实路由渲染测试 (MemoryRouter)
 *
 * 测试 <AppRoutes> 在不同身份下的页面渲染结果。
 * 使用 MemoryRouter + initialPath 精确控制路由，authStore 同步设置身份。
 * skipAuthInit=true 防止 AuthInitializer 覆盖预先设置的 store 状态。
 *
 * 覆盖:
 * - anonymous: / → login page, /manage → login
 * - user: /review → review center (in ShellLayout), /rules → 403, /manage → 403
 * - admin: /rules → rules center (in ShellLayout), /manage → system manage (in ShellLayout)
 * - /not-exist → 404 (in ShellLayout)
 * - token expired logout → clear state, null user
 * - ShellLayout renders header/sidebar for protected pages
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ConfigProvider, App as AntApp } from 'antd';
import { useAuthStore } from '../../stores/authStore';
import { AppRoutes } from '../../routes/AppRoutes';
import type { AuthUser } from '../../stores/authStore';

// ═══════════════════════════════════════════════════════════════
// 身份预设
// ═══════════════════════════════════════════════════════════════

const ADMIN_USER: AuthUser = {
  userId: 1,
  username: 'admin_test',
  role: 'admin',
  company: '测试公司',
  email: 'admin@test.com',
  permissions: [
    'file:upload', 'file:check', 'report:view', 'report:download', 'report:list_all',
    'rules:read', 'rules:write', 'rules:sync',
    'admin:users', 'admin:audit', 'admin:billing',
    'stats:dashboard', 'kg:read', 'kg:seed', 'crawler:read', 'crawler:trigger',
  ],
};

const USER_USER: AuthUser = {
  userId: 2,
  username: 'user_test',
  role: 'user',
  company: '',
  email: 'user@test.com',
  permissions: ['file:upload', 'file:check', 'report:view', 'report:download', 'rules:read', 'kg:read'],
};

function loginAsUser() {
  localStorage.setItem('token', 'valid-user-token');
  useAuthStore.setState({ user: USER_USER, loading: false, error: null });
}

function loginAsAdmin() {
  localStorage.setItem('token', 'valid-admin-token');
  useAuthStore.setState({ user: ADMIN_USER, loading: false, error: null });
}

function loginAsAnonymous() {
  localStorage.removeItem('token');
  useAuthStore.setState({ user: null, loading: false, error: null });
}

/** 渲染 AppRoutes (skipAuthInit 避免 Async effect 覆盖 preset) */
function renderRoute(path: string) {
  return render(
    <ConfigProvider>
      <AntApp>
        <AppRoutes initialPath={path} useMemoryRouter skipAuthInit />
      </AntApp>
    </ConfigProvider>,
  );
}

// ═══════════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════════

/** 断言页面标题可见 (使用 getAllByText 容忍面包屑中的重复文字) */
function expectTitle(text: string) {
  const els = screen.getAllByText(text);
  expect(els.length).toBeGreaterThan(0);
}

// ═══════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════

describe('App Routing RBAC (real render)', () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, loading: false, error: null });
    localStorage.clear();
  });

  // ── anonymous ──────────────────────────────────────────────────

  describe('anonymous (no token)', () => {
    beforeEach(loginAsAnonymous);

    it('anonymous / → login page', async () => {
      renderRoute('/');
      await waitFor(() => expect(screen.getByText('招标文件合规自检系统')).toBeDefined(), { timeout: 3000 });
    });

    it('anonymous /manage → login page, not admin', async () => {
      renderRoute('/manage');
      await waitFor(() => expect(screen.getByText('包合规')).toBeDefined(), { timeout: 3000 });
      expect(() => screen.getByText('系统管理')).toThrow();
    });
  });

  // ── user (role=user) ──────────────────────────────────────────

  describe('user (role=user)', () => {
    beforeEach(loginAsUser);

    it('user /review → 审查中心 page', async () => {
      renderRoute('/review');
      await waitFor(() => expectTitle('审查中心'), { timeout: 3000 });
      await waitFor(() => {
        expect(screen.getAllByText('包合规').length).toBeGreaterThan(0);
      }, { timeout: 3000 });
    });

    it('user /rules → 403', async () => {
      renderRoute('/rules');
      await waitFor(() => expect(screen.getByText('无访问权限')).toBeDefined(), { timeout: 3000 });
    });

    it('user /manage → 403', async () => {
      renderRoute('/manage');
      await waitFor(() => expect(screen.getByText('无访问权限')).toBeDefined(), { timeout: 3000 });
    });

    it('user /manage/audit → 403', async () => {
      renderRoute('/manage/audit');
      await waitFor(() => expect(screen.getByText('无访问权限')).toBeDefined(), { timeout: 3000 });
    });

    it('user isAdmin() = false', () => {
      expect(useAuthStore.getState().isAdmin()).toBe(false);
    });

    it('user role = "user"', () => {
      expect(useAuthStore.getState().role()).toBe('user');
    });
  });

  // ── admin (role=admin) ────────────────────────────────────────

  describe('admin (role=admin)', () => {
    beforeEach(loginAsAdmin);

    it('admin /rules → 规则中心 page', async () => {
      renderRoute('/rules');
      await waitFor(() => expectTitle('规则中心'), { timeout: 3000 });
      await waitFor(() => {
        expect(screen.getAllByText('包合规').length).toBeGreaterThan(0);
      }, { timeout: 3000 });
    });

    it('admin /manage → 系统管理 page', async () => {
      renderRoute('/manage');
      await waitFor(() => expectTitle('系统管理'), { timeout: 3000 });
      await waitFor(() => {
        expect(screen.getAllByText('包合规').length).toBeGreaterThan(0);
      }, { timeout: 3000 });
    });

    it('admin isAdmin() = true', () => {
      expect(useAuthStore.getState().isAdmin()).toBe(true);
    });

    it('admin has admin:users permission', () => {
      expect(useAuthStore.getState().hasPerm('admin:users')).toBe(true);
    });

    it('admin can access /review too', async () => {
      renderRoute('/review');
      await waitFor(() => expectTitle('审查中心'), { timeout: 3000 });
    });
  });

  // ── register flow ─────────────────────────────────────────────

  describe('register flow (ProtectedShell acceptance)', () => {
    it('registered user with valid store can access / without being redirected', async () => {
      // Simulate a freshly registered user — token + user both present
      localStorage.setItem('token', 'fresh-register-token');
      useAuthStore.setState({
        user: {
          userId: 10,
          username: '新用户',
          role: 'user',
          company: '',
          email: 'new@test.com',
          permissions: ['file:upload'],
        },
        loading: false,
        error: null,
      });

      renderRoute('/');
      await waitFor(() => {
        // Should see the ShellLayout header (包合规 appears) and NOT be on login page
        expect(screen.getAllByText('包合规').length).toBeGreaterThan(0);
      }, { timeout: 3000 });
    });

    it('registered user with token but no user state → redirect /login', async () => {
      // Simulate broken registration that wrote token but didn't set user
      localStorage.setItem('token', 'token-only-no-user');
      useAuthStore.setState({ user: null, loading: false, error: null });

      renderRoute('/');
      await waitFor(() => {
        expect(screen.getByText('招标文件合规自检系统')).toBeDefined();
      }, { timeout: 3000 });
    });
  });

  // ── edge cases ────────────────────────────────────────────────

  describe('edge cases', () => {
    it('/not-exist → 404', async () => {
      loginAsAdmin();
      renderRoute('/not-exist');
      await waitFor(() => {
        const els = screen.queryAllByText('页面不存在');
        expect(els.length).toBeGreaterThan(0);
      }, { timeout: 3000 });
    });

    it('protected pages render inside ShellLayout (header visible)', async () => {
      loginAsAdmin();
      renderRoute('/manage');
      await waitFor(() => {
        expect(screen.getAllByText('包合规').length).toBeGreaterThan(0);
      }, { timeout: 3000 });
    });

    it('public pages do NOT render ShellLayout header', async () => {
      loginAsAdmin();
      renderRoute('/forgot-password');
      await waitFor(() => {
        const searchInput = screen.queryByPlaceholderText(/搜索文件/);
        expect(searchInput).toBeNull();
      }, { timeout: 3000 });
    });

    it('logout clears token and user state', () => {
      loginAsAdmin();
      expect(useAuthStore.getState().user).not.toBeNull();

      useAuthStore.getState().logout();

      expect(localStorage.getItem('token')).toBeNull();
      expect(useAuthStore.getState().user).toBeNull();
      expect(useAuthStore.getState().role()).toBeNull();
    });

    it('/upload → redirect to /review', async () => {
      loginAsUser();
      renderRoute('/upload');
      await waitFor(() => expectTitle('审查中心'), { timeout: 3000 });
    });

    it('/history → redirect to /review/history', async () => {
      loginAsUser();
      renderRoute('/history');
      await waitFor(() => {
        const allText = document.body.textContent || '';
        expect(allText).toContain('审查中心');
      }, { timeout: 5000 });
    });

    it('/admin/rules → redirect to /rules', async () => {
      loginAsAdmin();
      renderRoute('/admin/rules');
      await waitFor(() => expectTitle('规则中心'), { timeout: 3000 });
    });

    it('/admin/panel → redirect to /manage', async () => {
      loginAsAdmin();
      renderRoute('/admin/panel');
      await waitFor(() => expectTitle('系统管理'), { timeout: 3000 });
    });
  });
});
