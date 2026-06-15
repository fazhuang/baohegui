/**
 * 权限上下文 — 全局提供当前用户信息和权限检查能力
 *
 * 包裹在 <BrowserRouter> 内部，<AppLayout> 外部。
 *
 * 使用方式:
 *   const { user, hasPerm, isAdmin, isSuperAdmin } = usePermission();
 */

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import type { CurrentUser, UserRole, PermissionKey } from '../types';
import { normalizeRole } from '../types';
import { hasPermission as checkPerm, isAdminRole, isSuperAdmin } from '../config/rbac';
import { getCurrentUser as fetchCurrentUser } from '../services/api';

interface PermissionContextValue {
  /** 当前用户信息（加载中时为 null） */
  user: CurrentUser | null;
  /** 加载状态 */
  loading: boolean;
  /** 检查当前用户是否拥有某权限 */
  hasPerm: (perm: PermissionKey) => boolean;
  /** 是否为管理员 */
  isAdmin: boolean;
  /** 是否为超级管理员 */
  isSuperAdmin: boolean;
  /** 当前角色 */
  role: UserRole | null;
  /** 刷新用户信息 */
  refresh: () => Promise<void>;
  /** 退出登录 */
  logout: () => void;
}

const PermissionContext = createContext<PermissionContextValue>({
  user: null,
  loading: true,
  hasPerm: () => false,
  isAdmin: false,
  isSuperAdmin: false,
  role: null,
  refresh: async () => {},
  logout: () => {},
});

export function PermissionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const loadUser = useCallback(async () => {
    const token = localStorage.getItem('token');
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      const data = await fetchCurrentUser();
      const u: CurrentUser = {
        userId: data.user_id,
        username: data.username,
        role: normalizeRole(data.role),
        company: data.company,
        email: data.email,
        permissions: data.permissions || [],
      };
      setUser(u);
      localStorage.setItem('role', u.role);
      localStorage.setItem('username', u.username);
    } catch {
      // token 过期/无效 → 保留本地信息作为回退
      const localRole = localStorage.getItem('role');
      const localUsername = localStorage.getItem('username');
      if (localRole) {
        setUser({
          userId: 0,
          username: localUsername || '',
          role: normalizeRole(localRole),
          company: '',
          email: '',
          permissions: [],
        });
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  const logout = useCallback(() => {
    localStorage.removeItem('token');
    localStorage.removeItem('role');
    localStorage.removeItem('username');
    setUser(null);
    navigate('/login', { replace: true });
  }, [navigate]);

  const value: PermissionContextValue = {
    user,
    loading,
    hasPerm: (perm: PermissionKey) => (user ? checkPerm(user.role, perm) : false),
    isAdmin: user ? isAdminRole(user.role) : false,
    isSuperAdmin: user ? isSuperAdmin(user.role) : false,
    role: user?.role ?? null,
    refresh: loadUser,
    logout,
  };

  return (
    <PermissionContext.Provider value={value}>
      {children}
    </PermissionContext.Provider>
  );
}

/** 消费权限上下文 */
export function usePermission(): PermissionContextValue {
  return useContext(PermissionContext);
}

export default PermissionContext;
