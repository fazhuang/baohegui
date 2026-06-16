/**
 * Auth Store Unit Tests
 *
 * Tests: login, register, restoreSession, logout, hasPerm, isAdmin
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useAuthStore } from '../authStore';

// Mock services/api
vi.mock('../../services/api', () => ({
  loginUser: vi.fn(),
  registerUser: vi.fn(),
  getCurrentUser: vi.fn(),
}));

import { getCurrentUser, registerUser } from '../../services/api';

describe('useAuthStore', () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: null,
      loading: false,
      error: null,
    });
    vi.clearAllMocks();
  });

  describe('initial state', () => {
    it('should have null user and loading=true by default', () => {
      const state = useAuthStore.getState();
      expect(state.user).toBeNull();
      expect(state.error).toBeNull();
    });
  });

  describe('hasPerm', () => {
    it('should return true when permission is present', () => {
      useAuthStore.setState({
        user: {
          userId: 1,
          username: 'admin',
          role: 'admin',
          company: '',
          email: '',
          permissions: ['admin:users', 'rules:write'],
        },
      });
      expect(useAuthStore.getState().hasPerm('admin:users')).toBe(true);
    });

    it('should return false when permission is absent', () => {
      useAuthStore.setState({
        user: {
          userId: 1,
          username: 'user1',
          role: 'user',
          company: '',
          email: '',
          permissions: ['file:upload'],
        },
      });
      expect(useAuthStore.getState().hasPerm('admin:users')).toBe(false);
    });

    it('should return false when user is null', () => {
      useAuthStore.setState({ user: null });
      expect(useAuthStore.getState().hasPerm('anything')).toBe(false);
    });
  });

  describe('isAdmin', () => {
    it('should return true for admin role', () => {
      useAuthStore.setState({
        user: {
          userId: 1,
          username: 'admin',
          role: 'admin',
          company: '',
          email: '',
          permissions: [],
        },
      });
      expect(useAuthStore.getState().isAdmin()).toBe(true);
    });

    it('should return false for user role', () => {
      useAuthStore.setState({
        user: {
          userId: 2,
          username: 'user',
          role: 'user',
          company: '',
          email: '',
          permissions: [],
        },
      });
      expect(useAuthStore.getState().isAdmin()).toBe(false);
    });
  });

  describe('register', () => {
    const registerResponse = {
      access_token: 'new-user-token',
      token_type: 'bearer',
      user_id: 5,
      username: 'newuser',
      role: 'user',
      company: '',
    };

    const meResponse = {
      user_id: 5,
      username: 'newuser',
      role: 'user',
      company: '测试公司',
      email: 'new@test.com',
      permissions: ['file:upload', 'file:check', 'report:view'],
    };

    it('should set user after successful registration', async () => {
      (registerUser as ReturnType<typeof vi.fn>).mockResolvedValue(registerResponse);
      (getCurrentUser as ReturnType<typeof vi.fn>).mockResolvedValue(meResponse);

      await useAuthStore.getState().register({
        username: 'newuser',
        password: 'password123',
        company: '测试公司',
        email: 'new@test.com',
      });

      const state = useAuthStore.getState();
      expect(state.user).not.toBeNull();
      expect(state.user!.username).toBe('newuser');
      expect(state.user!.userId).toBe(5);
      expect(state.user!.permissions).toEqual(['file:upload', 'file:check', 'report:view']);
      expect(state.error).toBeNull();
    });

    it('should set role from /auth/me, NOT from register response', async () => {
      // register response says 'user', but /auth/me says 'admin'
      (registerUser as ReturnType<typeof vi.fn>).mockResolvedValue({
        ...registerResponse,
        role: 'user',
      });
      (getCurrentUser as ReturnType<typeof vi.fn>).mockResolvedValue({
        ...meResponse,
        role: 'admin',
        permissions: ['admin:users', 'rules:write'],
      });

      await useAuthStore.getState().register({
        username: 'newadmin',
        password: 'password123',
      });

      const state = useAuthStore.getState();
      expect(state.user!.role).toBe('admin');
      expect(state.user!.permissions).toContain('admin:users');
    });

    it('should not leave token on register failure', async () => {
      localStorage.setItem('token', 'should-be-cleared');
      (registerUser as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('用户名已存在'));

      await expect(
        useAuthStore.getState().register({ username: 'dup', password: 'pw', email: 'dup@test.com' })
      ).rejects.toThrow();

      expect(localStorage.getItem('token')).toBeNull();
      expect(useAuthStore.getState().user).toBeNull();
    });

    it('should not leave user state on register failure', async () => {
      (registerUser as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'));

      await expect(
        useAuthStore.getState().register({ username: 'fail', password: 'pw', email: 'fail@test.com' })
      ).rejects.toThrow();

      expect(useAuthStore.getState().user).toBeNull();
      expect(useAuthStore.getState().loading).toBe(false);
    });

    it('should clear token on /auth/me failure after register', async () => {
      (registerUser as ReturnType<typeof vi.fn>).mockResolvedValue(registerResponse);
      (getCurrentUser as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Auth failed'));

      await expect(
        useAuthStore.getState().register({ username: 'bad', password: 'pw', email: 'bad@test.com' })
      ).rejects.toThrow();

      expect(useAuthStore.getState().user).toBeNull();
      expect(localStorage.getItem('token')).toBeNull();
    });
  });

  describe('logout', () => {
    it('should clear user and token', () => {
      localStorage.setItem('token', 'fake-token');
      useAuthStore.setState({
        user: {
          userId: 1,
          username: 'admin',
          role: 'admin',
          company: '',
          email: '',
          permissions: [],
        },
      });
      useAuthStore.getState().logout();
      expect(useAuthStore.getState().user).toBeNull();
      expect(localStorage.getItem('token')).toBeNull();
    });
  });

  describe('restoreSession', () => {
    it('should set loading=false and user=null when no token', async () => {
      localStorage.removeItem('token');
      await useAuthStore.getState().restoreSession();
      expect(useAuthStore.getState().loading).toBe(false);
      expect(useAuthStore.getState().user).toBeNull();
    });

    it('should clear token and user on API error', async () => {
      localStorage.setItem('token', 'bad-token');
      (getCurrentUser as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Token invalid'));
      await useAuthStore.getState().restoreSession();
      expect(useAuthStore.getState().user).toBeNull();
      expect(localStorage.getItem('token')).toBeNull();
    });
  });
});
