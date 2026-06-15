/**
 * DashboardPage — 按角色路由（懒加载子页面以控制 chunk 体积）
 *
 * admin → AdminDashboard (lazy)
 * user  → UserDashboard (lazy)
 */

import React, { Suspense, lazy } from 'react';
import { Spin } from 'antd';
import { useAuthStore } from '../stores/authStore';

const AdminDashboard = lazy(() => import('./dashboards/AdminDashboard'));
const UserDashboard = lazy(() => import('./dashboards/UserDashboard'));

const FB = <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}><Spin size="large" /></div>;

const DashboardPage: React.FC = () => {
  const role = useAuthStore(s => s.role());
  const loading = useAuthStore(s => s.loading);

  if (loading) return FB;

  if (role === 'admin') return <Suspense fallback={FB}><AdminDashboard /></Suspense>;
  return <Suspense fallback={FB}><UserDashboard /></Suspense>;
};

export default DashboardPage;
