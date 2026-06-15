/**
 * 规则管理后台 — 规则列表 / 同步管理 / 拦截反馈 / 系统看板
 *
 * 编排层：Tabs 导入 features/rules/components 下的独立 Tab 组件。
 */

import React from 'react';
import { Typography, Tabs } from 'antd';
import {
  SyncOutlined, WarningOutlined, FileAddOutlined,
  DashboardOutlined, SettingOutlined,
} from '@ant-design/icons';
import RuleListTab from '../features/rules/components/RuleListTab';
import SyncTab from '../features/rules/components/SyncTab';
import FeedbackTab from '../features/rules/components/FeedbackTab';
import DashboardTab from '../features/rules/components/DashboardTab';

const { Title } = Typography;

const AdminRulesPage: React.FC = () => (
  <div>
    <Title level={3} style={{ marginBottom: 16 }}><SettingOutlined style={{ marginRight: 8 }} />规则管理后台</Title>
    <Tabs defaultActiveKey="rules" items={[
      { key: 'rules', label: <span><FileAddOutlined /> 规则列表</span>, children: <RuleListTab /> },
      { key: 'sync', label: <span><SyncOutlined /> 同步管理</span>, children: <SyncTab /> },
      { key: 'feedback', label: <span><WarningOutlined /> 拦截反馈</span>, children: <FeedbackTab /> },
      { key: 'dashboard', label: <span><DashboardOutlined /> 系统看板</span>, children: <DashboardTab /> },
    ]} />
  </div>
);

export default AdminRulesPage;
