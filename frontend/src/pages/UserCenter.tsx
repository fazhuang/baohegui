/**
 * UserCenter — 用户中心容器
 *
 * 路由结构:
 *   /account              → 我的账户
 *   /account/subscription → 订阅管理
 */

import React from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Tabs } from 'antd';
import { UserOutlined, CrownOutlined } from '@ant-design/icons';
import PageHeader from '../components/PageHeader';

const TAB_ITEMS = [
  { key: '/account', label: '我的账户', icon: <UserOutlined /> },
  { key: '/account/subscription', label: '订阅管理', icon: <CrownOutlined /> },
];

const UserCenter: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const activeKey = TAB_ITEMS.find(item => location.pathname === item.key)?.key ?? '/account';

  return (
    <div>
      <PageHeader
        title="用户中心"
        subtitle="管理账户信息、订阅计划与使用配额"
        breadcrumb={[{ label: '用户中心' }]}
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

export default UserCenter;
