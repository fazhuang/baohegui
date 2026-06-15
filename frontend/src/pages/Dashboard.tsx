/**
 * DashboardPage — 按角色路由
 *
 * admin → AdminDashboard
 * user  → UserDashboard
 */

import React from 'react';
import { useAuthStore } from '../stores/authStore';
import AdminDashboard from './dashboards/AdminDashboard';
import UserDashboard from './dashboards/UserDashboard';

const DashboardPage: React.FC = () => {
  const role = useAuthStore(s => s.role());
  const loading = useAuthStore(s => s.loading);

  if (loading) return null;

  if (role === 'admin') return <AdminDashboard />;
  return <UserDashboard />;
};

export default DashboardPage;
