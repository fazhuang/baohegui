/**
 * Admin RBAC Tests — admin-only 路由权限与 API 访问测试
 *
 * 测试 admin/user 对管理相关 API 的权限差异。
 * 不使用真实后端，通过 mock /api/auth/me 返回不同身份验证权限策略。
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useAuthStore } from '../../../stores/authStore';

// ═══════════════════════════════════════════════════════════════
// Helpers — 快速设置 authStore 为不同身份
// ═══════════════════════════════════════════════════════════════

function setStoreAsAdmin() {
  useAuthStore.setState({
    user: {
      userId: 1,
      username: 'admin',
      role: 'admin',
      company: '',
      email: 'admin@test.com',
      permissions: [
        'file:upload', 'file:check',
        'report:view', 'report:download', 'report:list_all',
        'rules:read', 'rules:write', 'rules:sync',
        'admin:users', 'admin:audit', 'admin:billing',
        'stats:dashboard',
        'kg:read', 'kg:seed',
        'crawler:read', 'crawler:trigger',
      ],
    },
    loading: false,
    error: null,
  });
}

function setStoreAsUser() {
  useAuthStore.setState({
    user: {
      userId: 2,
      username: 'user',
      role: 'user',
      company: '',
      email: 'user@test.com',
      permissions: ['file:upload', 'file:check', 'report:view', 'report:download', 'rules:read', 'kg:read'],
    },
    loading: false,
    error: null,
  });
}

function setStoreAsAnonymous() {
  useAuthStore.setState({
    user: null,
    loading: false,
    error: null,
  });
}

// ═══════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════

describe('Admin RBAC', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: null, loading: false, error: null });
  });

  // ── admin 身份 ─────────────────────────────────────────────────

  describe('admin identity', () => {
    beforeEach(() => setStoreAsAdmin());

    it('admin has admin role', () => {
      expect(useAuthStore.getState().role()).toBe('admin');
    });

    it('admin isAdmin() = true', () => {
      expect(useAuthStore.getState().isAdmin()).toBe(true);
    });

    it('admin has admin:users permission', () => {
      expect(useAuthStore.getState().hasPerm('admin:users')).toBe(true);
    });

    it('admin has admin:audit permission', () => {
      expect(useAuthStore.getState().hasPerm('admin:audit')).toBe(true);
    });

    it('admin has admin:billing permission', () => {
      expect(useAuthStore.getState().hasPerm('admin:billing')).toBe(true);
    });

    it('admin has rules:write permission', () => {
      expect(useAuthStore.getState().hasPerm('rules:write')).toBe(true);
    });

    it('admin has rules:sync permission', () => {
      expect(useAuthStore.getState().hasPerm('rules:sync')).toBe(true);
    });

    it('admin has file:upload permission', () => {
      expect(useAuthStore.getState().hasPerm('file:upload')).toBe(true);
    });
  });

  // ── user 身份 ──────────────────────────────────────────────────

  describe('user identity', () => {
    beforeEach(() => setStoreAsUser());

    it('user has user role', () => {
      expect(useAuthStore.getState().role()).toBe('user');
    });

    it('user isAdmin() = false', () => {
      expect(useAuthStore.getState().isAdmin()).toBe(false);
    });

    it('user does NOT have admin:users permission', () => {
      expect(useAuthStore.getState().hasPerm('admin:users')).toBe(false);
    });

    it('user does NOT have admin:audit permission', () => {
      expect(useAuthStore.getState().hasPerm('admin:audit')).toBe(false);
    });

    it('user does NOT have admin:billing permission', () => {
      expect(useAuthStore.getState().hasPerm('admin:billing')).toBe(false);
    });

    it('user does NOT have rules:write permission', () => {
      expect(useAuthStore.getState().hasPerm('rules:write')).toBe(false);
    });

    it('user does NOT have rules:sync permission', () => {
      expect(useAuthStore.getState().hasPerm('rules:sync')).toBe(false);
    });

    it('user HAS file:upload permission', () => {
      expect(useAuthStore.getState().hasPerm('file:upload')).toBe(true);
    });

    it('user HAS report:view permission', () => {
      expect(useAuthStore.getState().hasPerm('report:view')).toBe(true);
    });
  });

  // ── anonymous 身份 ─────────────────────────────────────────────

  describe('anonymous identity', () => {
    beforeEach(() => setStoreAsAnonymous());

    it('anonymous role() = null', () => {
      expect(useAuthStore.getState().role()).toBeNull();
    });

    it('anonymous isAdmin() = false', () => {
      expect(useAuthStore.getState().isAdmin()).toBe(false);
    });

    it('anonymous hasPerm() always returns false', () => {
      expect(useAuthStore.getState().hasPerm('file:upload')).toBe(false);
      expect(useAuthStore.getState().hasPerm('admin:users')).toBe(false);
      expect(useAuthStore.getState().hasPerm('anything')).toBe(false);
    });
  });

  // ── logout 一致性 ──────────────────────────────────────────────

  describe('logout consistency', () => {
    it('logout clears admin state completely', () => {
      setStoreAsAdmin();
      expect(useAuthStore.getState().isAdmin()).toBe(true);

      useAuthStore.getState().logout();

      expect(useAuthStore.getState().user).toBeNull();
      expect(useAuthStore.getState().isAdmin()).toBe(false);
      expect(useAuthStore.getState().role()).toBeNull();
    });

    it('logout clears user state completely', () => {
      setStoreAsUser();
      expect(useAuthStore.getState().role()).toBe('user');

      useAuthStore.getState().logout();

      expect(useAuthStore.getState().user).toBeNull();
      expect(useAuthStore.getState().role()).toBeNull();
    });
  });
});
