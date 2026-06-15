/**
 * 管理后台 — 用户管理 / 审计日志 / 文件对比 / 计费面板
 *
 * 编排层：Tabs 导入 features/admin/components 下的独立 Tab 组件。
 */

import React, { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Tabs, Typography } from 'antd';
import { UserOutlined, AuditOutlined, SwapOutlined, DollarOutlined } from '@ant-design/icons';
import UserManageTab from '../features/admin/components/UserManageTab';
import AuditLogTab from '../features/admin/components/AuditLogTab';
import CompareTab from '../features/admin/components/CompareTab';
import BillingTab from '../features/admin/components/BillingTab';

const { Title } = Typography;

const AdminPanel: React.FC = () => {
  const [searchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') || 'users');

  return (
    <div>
      <Title level={3}>管理中心</Title>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
        { key: 'users', label: <span><UserOutlined /> 用户管理</span>, children: <UserManageTab /> },
        { key: 'audit', label: <span><AuditOutlined /> 审计日志</span>, children: <AuditLogTab /> },
        { key: 'compare', label: <span><SwapOutlined /> 文件对比</span>, children: <CompareTab /> },
        { key: 'billing', label: <span><DollarOutlined /> 计费面板</span>, children: <BillingTab /> },
      ]} />
    </div>
  );
};

export default AdminPanel;
