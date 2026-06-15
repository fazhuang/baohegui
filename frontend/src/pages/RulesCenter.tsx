/**
 * RulesCenter — 规则中心容器
 *
 * 通过内部 Tabs 子页面导航，整合规则列表、编辑、版本、同步等功能。
 *
 * 路由结构:
 *   /rules           → RulesDashboard (规则列表 + 系统看板)
 *   /rules/editor    → RulesEditor
 *   /rules/versions  → RulesVersion
 *   /rules/sync      → SyncTab
 *   /rules/industry  → 行业配置 (ComingSoon)
 */

import React from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Tabs } from 'antd';
import {
  FileAddOutlined, SyncOutlined, HistoryOutlined,
  EditOutlined, ApartmentOutlined,
} from '@ant-design/icons';
import PageHeader from '../components/PageHeader';

const TAB_ITEMS = [
  { key: '/rules', label: '规则总览', icon: <FileAddOutlined /> },
  { key: '/rules/editor', label: '编辑器', icon: <EditOutlined /> },
  { key: '/rules/versions', label: '版本管理', icon: <HistoryOutlined /> },
  { key: '/rules/sync', label: '同步管理', icon: <SyncOutlined /> },
  { key: '/rules/industry', label: '行业配置', icon: <ApartmentOutlined /> },
];

const RulesCenter: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const activeKey = TAB_ITEMS.find(item => location.pathname === item.key)?.key ?? '/rules';

  return (
    <div>
      <PageHeader
        title="规则中心"
        subtitle="管理合规审查规则、同步平台规则、配置行业参数"
        breadcrumb={[{ label: '规则中心' }]}
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

export default RulesCenter;
