/**
 * KnowledgeBase — 知识库容器
 *
 * 路由结构:
 *   /kg        → 知识图谱概览
 *   /kg/cases  → 案例库
 *   /kg/legal  → 法规库
 */

import React from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Tabs } from 'antd';
import { NodeIndexOutlined, FolderOpenOutlined, BookOutlined } from '@ant-design/icons';
import PageHeader from '../components/PageHeader';

const TAB_ITEMS = [
  { key: '/kg', label: '知识图谱', icon: <NodeIndexOutlined /> },
  { key: '/kg/cases', label: '案例库', icon: <FolderOpenOutlined /> },
  { key: '/kg/legal', label: '法规库', icon: <BookOutlined /> },
];

const KnowledgeBase: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const activeKey = TAB_ITEMS.find(item => location.pathname === item.key)?.key ?? '/kg';

  return (
    <div>
      <PageHeader
        title="知识库"
        subtitle="招标投标知识图谱、投诉案例与法规依据"
        breadcrumb={[{ label: '知识库' }]}
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

export default KnowledgeBase;
