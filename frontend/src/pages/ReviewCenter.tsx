/**
 * ReviewCenter — 审查中心容器
 *
 * 提供"新建审查"和"审查历史"两个子页面的 Tab 式导航。
 *
 * 路由结构:
 *   /review          → UploadPage (新建审查)
 *   /review/history  → HistoryPage (审查历史)
 */

import React from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Tabs } from 'antd';
import { UploadOutlined, HistoryOutlined } from '@ant-design/icons';
import PageHeader from '../components/PageHeader';

const TAB_ITEMS = [
  { key: '/review', label: '新建审查', icon: <UploadOutlined /> },
  { key: '/review/history', label: '审查历史', icon: <HistoryOutlined /> },
];

const ReviewCenter: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const activeKey = location.pathname === '/review/history' ? '/review/history' : '/review';

  return (
    <div>
      <PageHeader
        title="审查中心"
        subtitle="上传招标文件并进行合规审查"
        breadcrumb={[{ label: '审查中心' }]}
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

export default ReviewCenter;
