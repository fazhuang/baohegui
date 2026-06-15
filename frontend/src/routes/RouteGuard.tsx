import React from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { Result, Button } from 'antd';
import { usePermission } from '../contexts/PermissionContext';
import type { UserRole, PermissionKey } from '../types';

interface RouteGuardProps {
  roles?: UserRole[];
  permissions?: PermissionKey[];
  children?: React.ReactNode;
}

const RouteGuard: React.FC<RouteGuardProps> = ({ roles, permissions, children }) => {
  const { user, hasPerm, role } = usePermission();

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (permissions && permissions.length > 0) {
    const ok = permissions.some((p) => hasPerm(p));
    if (!ok) return <ForbiddenResult />;
  }

  if (roles && roles.length > 0) {
    if (role && !roles.includes(role)) return <ForbiddenResult />;
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
