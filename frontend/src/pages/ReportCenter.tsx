/**
 * ReportCenter — 报告中心容器
 *
 * 路由结构:
 *   /reports           → 报告列表
 *   /reports/feedback  → 反馈管理 (admin/reviewer)
 */

import React from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Tabs } from 'antd';
import { FileTextOutlined, CommentOutlined } from '@ant-design/icons';
import { useAuthStore } from '../stores/authStore';
import PageHeader from '../components/PageHeader';

const ReportCenter: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const isAdmin = useAuthStore(s => s.isAdmin());
  const canReview = isAdmin;

  const items = [
    { key: '/reports', label: '报告列表', icon: <FileTextOutlined /> },
    ...(canReview
      ? [{ key: '/reports/feedback', label: '反馈管理', icon: <CommentOutlined /> }]
      : []),
  ];

  const activeKey = items.find(item => location.pathname === item.key)?.key ?? '/reports';

  return (
    <div>
      <PageHeader
        title="报告中心"
        subtitle="查看、下载和反馈合规审查报告"
        breadcrumb={[{ label: '报告中心' }]}
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

export default ReportCenter;
