/**
 * DashboardPage — 按角色路由
 *
 * super_admin → SuperAdminDashboard
 * admin       → AdminDashboard
 * 其他         → UserDashboard (agent / enterprise / reviewer)
 */

import React from 'react';
import { usePermission } from '../contexts/PermissionContext';
import SuperAdminDashboard from './dashboards/SuperAdminDashboard';
import AdminDashboard from './dashboards/AdminDashboard';
import UserDashboard from './dashboards/UserDashboard';

const DashboardPage: React.FC = () => {
  const { role, loading } = usePermission();

  if (loading) return null;

  if (role === 'super_admin') return <SuperAdminDashboard />;
  if (role === 'admin') return <AdminDashboard />;
  return <UserDashboard />;
};

export default DashboardPage;
