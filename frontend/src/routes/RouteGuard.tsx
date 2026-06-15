import React from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { Result, Button } from 'antd';
import { useAuthStore } from '../stores/authStore';
import type { UserRole, PermissionKey } from '../types';

interface RouteGuardProps {
  roles?: UserRole[];
  permissions?: PermissionKey[];
  children?: React.ReactNode;
}

/**
 * RouteGuard — 路由权限守卫
 *
 * requiredRoles 语义:
 *   undefined   → 不传（renderRoutes 不调用 RouteGuard）
 *   []          → 已验证但禁止访问 (403)
 *   ['admin']   → 仅 admin
 *   ['admin','user'] → 所有已登录用户
 */
const RouteGuard: React.FC<RouteGuardProps> = ({ roles, permissions, children }) => {
  const user = useAuthStore(s => s.user);
  const hasPermFn = useAuthStore(s => s.hasPerm);
  const roleVal = useAuthStore(s => s.role());

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  // [] = 需要登录但禁止访问
  if (roles && roles.length === 0) {
    return <ForbiddenResult />;
  }

  if (permissions && permissions.length > 0) {
    const ok = permissions.some(p => hasPermFn(p));
    if (!ok) return <ForbiddenResult />;
  }

  if (roles && roles.length > 0) {
    if (roleVal && !roles.includes(roleVal)) return <ForbiddenResult />;
  }

  return children ? <>{children}</> : <Outlet />;
};

function ForbiddenResult() {
  return (
    <Result
      status="403"
      title="无访问权限"
      subTitle="你没有访问此页面的权限。如需帮助，请联系系统管理员。"
      extra={<Button type="primary" onClick={() => window.history.back()}>返回上一页</Button>}
    />
  );
}

export default RouteGuard;
