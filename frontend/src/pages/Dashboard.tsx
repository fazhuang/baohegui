/**
 * DashboardPage — 按角色路由
 *
 * admin → AdminDashboard
 * user  → UserDashboard
 */

import React from 'react';
import { usePermission } from '../contexts/PermissionContext';
import AdminDashboard from './dashboards/AdminDashboard';
import UserDashboard from './dashboards/UserDashboard';

const DashboardPage: React.FC = () => {
  const { role, loading } = usePermission();

  if (loading) return null;

  if (role === 'admin') return <AdminDashboard />;
  return <UserDashboard />;
};

export default DashboardPage;
