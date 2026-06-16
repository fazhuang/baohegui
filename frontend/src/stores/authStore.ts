/**
 * Auth Store — 用户身份状态 (zustand)
 *
 * 唯一权限来源：/api/auth/me 返回结果。
 * 不信任 localStorage.role / localStorage.username。
 * 非测试代码中，只有此文件可以写 localStorage token。
 */

import { create } from 'zustand';
import type { UserRole } from '../types';
import { getCurrentUser, loginUser as apiLogin, registerUser as apiRegister, type LoginParams, type CurrentUserResponse } from '../services/api';
import { mapServerRole } from '../permissions/permissions';

export interface AuthUser {
  userId: number;
  username: string;
  role: UserRole;
  company: string;
  email: string;
  permissions: string[];
}

export interface RegisterParams {
  username: string;
  password: string;
  company?: string;
  email?: string;
}

interface AuthState {
  user: AuthUser | null;
  loading: boolean;
  error: string | null;
  /** 登录 */
  login: (params: LoginParams) => Promise<void>;
  /** 注册 */
  register: (params: RegisterParams) => Promise<void>;
  /** 从 token 恢复 session */
  restoreSession: () => Promise<void>;
  /** 退出 */
  logout: () => void;
  /** 是否有某权限 */
  hasPerm: (perm: string) => boolean;
  /** 是否为 admin */
  isAdmin: () => boolean;
  /** 当前角色 */
  role: () => UserRole | null;
}

/** 从 /auth/me 响应构建 AuthUser，避免重复 */
function buildUser(me: CurrentUserResponse): AuthUser {
  const perms: string[] = me.permissions || [];
  return {
    userId: me.user_id,
    username: me.username,
    role: mapServerRole(me.role),
    company: me.company || '',
    email: me.email || '',
    permissions: perms,
  };
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  loading: true,
  error: null,

  login: async (params: LoginParams) => {
    set({ loading: true, error: null });
    try {
      const result = await apiLogin(params);
      localStorage.setItem('token', result.access_token);
      const me: CurrentUserResponse = await getCurrentUser();
      set({ user: buildUser(me), loading: false });
    } catch (e: unknown) {
      localStorage.removeItem('token');
      const msg = e instanceof Error ? e.message : '登录失败';
      set({ error: msg, loading: false });
      throw e;
    }
  },

  register: async (params: RegisterParams) => {
    set({ loading: true, error: null });
    try {
      const result = await apiRegister(params);
      localStorage.setItem('token', result.access_token);
      // 注册后立即获取完整用户信息 — 角色来自 /auth/me，不猜测 register 响应
      const me: CurrentUserResponse = await getCurrentUser();
      set({ user: buildUser(me), loading: false });
    } catch (e: unknown) {
      // 注册失败不残留 token
      localStorage.removeItem('token');
      const msg = e instanceof Error ? e.message : '注册失败';
      set({ error: msg, loading: false });
      throw e;
    }
  },

  restoreSession: async () => {
    const token = localStorage.getItem('token');
    if (!token) {
      set({ loading: false, user: null });
      return;
    }
    set({ loading: true });
    try {
      const me: CurrentUserResponse = await getCurrentUser();
      set({ user: buildUser(me), loading: false });
    } catch {
      localStorage.removeItem('token');
      set({ user: null, loading: false });
    }
  },

  logout: () => {
    localStorage.removeItem('token');
    set({ user: null, loading: false, error: null });
  },

  hasPerm: (perm: string) => {
    const { user } = get();
    return user?.permissions.includes(perm) ?? false;
  },

  isAdmin: () => {
    const { user } = get();
    return user?.role === 'admin';
  },

  role: () => {
    const { user } = get();
    return user?.role ?? null;
  },
}));
