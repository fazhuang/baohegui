/**
 * Announcements — 警示公告页面
 *
 * 路由结构:
 *   /announcements         → 公告列表
 *   /announcements/manage  → 公告管理 (admin)
 */

import React from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Tabs } from 'antd';
import { NotificationOutlined, SettingOutlined } from '@ant-design/icons';
import { usePermission } from '../contexts/PermissionContext';
import PageHeader from '../components/PageHeader';

const Announcements: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { isAdmin } = usePermission();

  const items = [
    { key: '/announcements', label: '公告列表', icon: <NotificationOutlined /> },
    ...(isAdmin
      ? [{ key: '/announcements/manage', label: '公告管理', icon: <SettingOutlined /> }]
      : []),
  ];

  const activeKey = items.find(item => location.pathname === item.key)?.key ?? '/announcements';

  return (
    <div>
      <PageHeader
        title="警示公告"
        subtitle="招标投标违规案例通报与合规警示"
        breadcrumb={[{ label: '警示公告' }]}
      />
      <Tabs
        activeKey={activeKey}
        onChange={key => navigate(key)}
        items={items.map(item => ({
          ...item,
          children: null,
        }))}
        style={{ marginBottom: 16 }}
      />
      <Outlet />
    </div>
  );
};

export default Announcements;
