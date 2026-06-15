/**
 * @deprecated 已废弃 — 路由权限已由 renderRoutes.tsx 统一套用 RouteGuard，不再需要此组件。
 *
 * 保留本文件仅供历史参考。
 */

import React from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { Result, Button } from 'antd';
import { useAuthStore } from '../stores/authStore';
import type { UserRole } from '../types';

interface RequireRoleProps {
  roles: UserRole[];
  redirectTo?: string;
}

const RequireRole: React.FC<RequireRoleProps> = ({ roles, redirectTo }) => {
  const user = useAuthStore(s => s.user);
  const roleVal = useAuthStore(s => s.role());

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (roleVal && roles.includes(roleVal)) {
    return <Outlet />;
  }

  if (redirectTo) {
    return <Navigate to={redirectTo} replace />;
  }

  return (
    <Result
      status="403"
      title="无访问权限"
      subTitle="你没有访问此页面的权限。如需帮助，请联系系统管理员。"
      extra={
        <Button type="primary" onClick={() => window.history.back()}>
          返回上一页
        </Button>
      }
    />
  );
};

export default RequireRole;
