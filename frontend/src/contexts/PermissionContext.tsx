/**
 * 权限上下文 — 服务端权限驱动的统一用户状态
 *
 * 核心原则:
 * 1. /auth/me 失败 → 清空 token → 跳转 login → 不渲染任何受保护页面
 * 2. 权限来源只有一个: 服务端返回的 permissions 数组
 * 3. localStorage 只存 token，不存 role/username（仅 saved_username 用于登录页回显）
 * 4. role 来自服务端真实字段 (admin / user)
 * 5. isSuperAdmin 必须来自服务端显式字段，禁止从 permissions 推导
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
  /** 是否为管理员 (来自服务端 role 字段) */
  isAdmin: boolean;
  /** 是否为超级管理员 (来自服务端 is_super_admin 字段) */
  isSuperAdmin: boolean;
  /** 当前角色 (来自服务端) */
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
  /** 后端 is_super_admin 字段 (暂未落地，默认 false) */
  isSuperAdmin: boolean;
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
      const perms: string[] = data.permissions || [];
      const serverRole = mapServerRole(data.role);
      // 后端当前无 is_super_admin 字段，默认 false
      const superAdmin: boolean = data.is_super_admin === true;
      setUser({
        userId: data.user_id,
        username: data.username,
        role: serverRole,
        company: data.company || '',
        email: data.email || '',
        permissions: perms,
        isSuperAdmin: superAdmin,
      });
    } catch {
      // token 无效/过期 — 清空所有本地状态
      localStorage.removeItem('token');
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
    setUser(null);
    navigate('/login', { replace: true });
  }, [navigate]);

  const perms = user?.permissions ?? [];
  const currentRole = user?.role ?? null;

  const value: PermissionContextValue = {
    user,
    loading,
    hasPerm: (perm: PermissionKey) => hasPermission(perms, perm),
    isAdmin: isAdminLike(perms, currentRole),
    isSuperAdmin: isSuperAdminLike(perms, currentRole),
    role: currentRole,
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
