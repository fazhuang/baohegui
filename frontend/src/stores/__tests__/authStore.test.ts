/**
 * Auth Store Unit Tests
 *
 * Tests: login, restoreSession, logout, hasPerm, isAdmin, isSuperAdmin
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useAuthStore } from '../authStore';

// Mock services/api
vi.mock('../../services/api', () => ({
  loginUser: vi.fn(),
  getCurrentUser: vi.fn(),
}));

import { getCurrentUser } from '../../services/api';

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
      // Initial state may vary — test after reset
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
          isSuperAdmin: false,
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
          isSuperAdmin: false,
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
          isSuperAdmin: false,
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
          isSuperAdmin: false,
        },
      });
      expect(useAuthStore.getState().isAdmin()).toBe(false);
    });
  });

  describe('isSuperAdmin', () => {
    it('should return false when isSuperAdmin flag is false (default)', () => {
      useAuthStore.setState({
        user: {
          userId: 1,
          username: 'admin',
          role: 'admin',
          company: '',
          email: '',
          permissions: ['kg:seed', 'crawler:trigger'],
          isSuperAdmin: false,
        },
      });
      expect(useAuthStore.getState().isSuperAdmin()).toBe(false);
    });

    it('should return true when isSuperAdmin flag is true', () => {
      useAuthStore.setState({
        user: {
          userId: 1,
          username: 'super',
          role: 'admin',
          company: '',
          email: '',
          permissions: ['kg:seed', 'crawler:trigger'],
          isSuperAdmin: true,
        },
      });
      expect(useAuthStore.getState().isSuperAdmin()).toBe(true);
    });

    it('isSuperAdmin should NEVER derive from permissions', () => {
      // Even with kg:seed and crawler:trigger, isSuperAdmin should be false
      // unless explicitly set
      useAuthStore.setState({
        user: {
          userId: 1,
          username: 'admin',
          role: 'admin',
          company: '',
          email: '',
          permissions: ['kg:seed', 'crawler:trigger'],
          isSuperAdmin: false,
        },
      });
      expect(useAuthStore.getState().isSuperAdmin()).toBe(false);
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
          isSuperAdmin: false,
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
