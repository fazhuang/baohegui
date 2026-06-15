/**
 * OpsCenter — 运维中心容器
 *
 * 仅 super_admin 可访问。
 *
 * 路由结构:
 *   /ops            → 运维概览
 *   /ops/scheduler  → 规则同步调度
 *   /ops/crawler    → 案例采集引擎
 *   /ops/kg-seed    → 知识图谱播种
 *   /ops/health     → 系统健康
 */

import React from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Tabs } from 'antd';
import {
  DashboardOutlined, ScheduleOutlined, CloudDownloadOutlined,
  ClusterOutlined, HeartOutlined,
} from '@ant-design/icons';
import PageHeader from '../components/PageHeader';

const TAB_ITEMS = [
  { key: '/ops', label: '运维概览', icon: <DashboardOutlined /> },
  { key: '/ops/scheduler', label: '同步调度', icon: <ScheduleOutlined /> },
  { key: '/ops/crawler', label: '案例采集', icon: <CloudDownloadOutlined /> },
  { key: '/ops/kg-seed', label: '图谱播种', icon: <ClusterOutlined /> },
  { key: '/ops/health', label: '系统健康', icon: <HeartOutlined /> },
];

const OpsCenter: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const activeKey = TAB_ITEMS.find(item => location.pathname === item.key)?.key ?? '/ops';

  return (
    <div>
      <PageHeader
        title="运维中心"
        subtitle="规则同步、案例采集、知识图谱播种与系统健康监控"
        breadcrumb={[{ label: '运维中心' }]}
      />
      <Tabs
        activeKey={activeKey}
        onChange={key => navigate(key)}
        items={TAB_ITEMS.map(item => ({
          ...item,
          children: null,
        }))}
        style={{ marginBottom: 16 }}
      />
      <Outlet />
    </div>
  );
};

export default OpsCenter;
