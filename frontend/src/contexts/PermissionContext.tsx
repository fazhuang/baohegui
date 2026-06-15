/**
 * 权限上下文 — 服务端权限驱动的统一用户状态
 *
 * 核心原则:
 * 1. /auth/me 失败 → 清空 token → 跳转 login → 不渲染任何受保护页面
 * 2. 权限来源只有一个: 服务端返回的 permissions 数组
 * 3. localStorage 只存 token 和 remember_me，不存 role/username
 * 4. role 仅用于展示目的，不作为权限判断依据
 */

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import type { UserRole, PermissionKey } from '../types';
import { getCurrentUser } from '../services/api';
import { mapServerRole, hasPermission, isAdminLike, isSuperAdminLike } from '../permissions/permissions';

interface PermissionContextValue {
  /** 当前用户信息 (null = 未登录 / 加载中) */
  user: CurrentUser | null;
  /** true 表示正在从服务端加载用户信息 */
  loading: boolean;
  /** 检查当前用户是否拥有某权限 (基于服务端 permissions) */
  hasPerm: (perm: PermissionKey) => boolean;
  /** 是否为管理员 (从 permissions 推导) */
  isAdmin: boolean;
  /** 是否为超级管理员 (从 permissions 推导) */
  isSuperAdmin: boolean;
  /** 当前角色 (仅展示用) */
  role: UserRole | null;
  /** 退出登录 */
  logout: () => void;
}

export interface CurrentUser {
  userId: number;
  username: string;
  role: UserRole;
  company: string;
  email: string;
  permissions: string[];
}

const PermissionContext = createContext<PermissionContextValue>({
  user: null,
  loading: true,
  hasPerm: () => false,
  isAdmin: false,
  isSuperAdmin: false,
  role: null,
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
      const data = await getCurrentUser();
      const perms = data.permissions || [];
      setUser({
        userId: data.user_id,
        username: data.username,
        role: mapServerRole(data.role),
        company: data.company || '',
        email: data.email || '',
        permissions: perms,
      });
      // 仅保存展示所需的 username (不做权限依据)
      localStorage.setItem('saved_username', data.username);
    } catch {
      // token 无效/过期 — 清空所有本地状态
      localStorage.removeItem('token');
      localStorage.removeItem('saved_username');
      navigate('/login', { replace: true });
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  const logout = useCallback(() => {
    localStorage.removeItem('token');
    localStorage.removeItem('saved_username');
    setUser(null);
    navigate('/login', { replace: true });
  }, [navigate]);

  const perms = user?.permissions ?? [];

  const value: PermissionContextValue = {
    user,
    loading,
    hasPerm: (perm: PermissionKey) => hasPermission(perms, perm),
    isAdmin: isAdminLike(perms),
    isSuperAdmin: isSuperAdminLike(perms),
    role: user?.role ?? null,
    logout,
  };

  return (
    <PermissionContext.Provider value={value}>
      {children}
    </PermissionContext.Provider>
  );
}

export function usePermission(): PermissionContextValue {
  return useContext(PermissionContext);
}

export default PermissionContext;
