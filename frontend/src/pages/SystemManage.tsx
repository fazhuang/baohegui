/**
 * SystemManage — 系统管理容器
 *
 * admin 可访问标准 Tabs (用户/审计/配额)
 *
 * 以下 4 个 Tab 需要 isSuperAdmin 才可见 (后端 is_super_admin 字段尚未落地, 当前对所有 admin 隐藏):
 * /manage/roles, /manage/config, /manage/security, /manage/model
 */

import React from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Tabs } from 'antd';
import {
  UserOutlined, AuditOutlined, FundOutlined,
  TeamOutlined, SettingOutlined, SafetyOutlined, RobotOutlined,
} from '@ant-design/icons';
import { useAuthStore } from '../stores/authStore';
import PageHeader from '../components/PageHeader';

const SystemManage: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const isSuperAdmin = useAuthStore(s => s.isSuperAdmin());

  const items = [
    { key: '/manage', label: '用户管理', icon: <UserOutlined /> },
    { key: '/manage/audit', label: '审计日志', icon: <AuditOutlined /> },
    { key: '/manage/quota', label: '配额管理', icon: <FundOutlined /> },
    ...(isSuperAdmin
      ? [
          { key: '/manage/roles', label: '角色管理', icon: <TeamOutlined /> },
          { key: '/manage/config', label: '系统配置', icon: <SettingOutlined /> },
          { key: '/manage/model', label: '模型配置', icon: <RobotOutlined /> },
          { key: '/manage/security', label: '安全中心', icon: <SafetyOutlined /> },
        ]
      : []),
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
