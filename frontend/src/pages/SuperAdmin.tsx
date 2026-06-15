/**
 * SuperAdmin — 超级管理员看板
 *
 * 仅 super_admin 可访问。展示全局审查量、活跃用户、Token 消耗、系统健康等。
 * 当前重定向至 SuperAdminDashboard 组件。
 */

import React from 'react';
import PageHeader from '../components/PageHeader';
import SuperAdminDashboard from './dashboards/SuperAdminDashboard';

const SuperAdmin: React.FC = () => {
  return (
    <div>
      <PageHeader
        title="超级管理员看板"
        subtitle="全局系统状态、用量统计与运维概览"
        breadcrumb={[{ label: '运维中心' }, { label: '超级管理员看板' }]}
      />
      <SuperAdminDashboard />
    </div>
  );
};

export default SuperAdmin;
