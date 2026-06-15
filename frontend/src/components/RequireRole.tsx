/**
 * 角色守卫路由组件
 *
 * 使用方式:
 *   <Route element={<RequireRole roles={['super_admin', 'admin']} />}>
 *     <Route path="manage" element={<SystemManage />} />
 *   </Route>
 *
 *   <Route element={<RequireRole roles={['super_admin']} />}>
 *     <Route path="ops" element={<OpsCenter />} />
 *   </Route>
 */

import React from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { Result, Button } from 'antd';
import { usePermission } from '../contexts/PermissionContext';
import type { UserRole } from '../types';

interface RequireRoleProps {
  roles: UserRole[];
  /** 如果无权限，重定向到此路径（默认不走，展示 403 页面） */
  redirectTo?: string;
}

const RequireRole: React.FC<RequireRoleProps> = ({ roles, redirectTo }) => {
  const { user, role } = usePermission();

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (role && roles.includes(role)) {
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
