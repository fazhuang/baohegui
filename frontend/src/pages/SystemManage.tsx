/**
 * SystemManage — 系统管理容器
 *
 * admin 可访问标准 Tabs (用户/审计/配额)
 */

import React from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Tabs } from 'antd';
import { UserOutlined, AuditOutlined, FundOutlined } from '@ant-design/icons';
import PageHeader from '../components/PageHeader';

const SystemManage: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const items = [
    { key: '/manage', label: '用户管理', icon: <UserOutlined /> },
    { key: '/manage/audit', label: '审计日志', icon: <AuditOutlined /> },
    { key: '/manage/quota', label: '配额管理', icon: <FundOutlined /> },
  ];

  const activeKey = items.find(item => location.pathname === item.key)?.key ?? '/manage';

  return (
    <div>
      <PageHeader
        title="系统管理"
        subtitle="用户、审计、配额与系统配置"
        breadcrumb={[{ label: '系统管理' }]}
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

export default SystemManage;
