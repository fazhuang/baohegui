/**
 * AuditLogTab — 审计日志 Tab 组件
 *
 * 从 AdminPanel.tsx 拆分。
 */

import React from 'react';
import { Table, Tag, Button, Typography } from 'antd';
import { AuditOutlined, ReloadOutlined } from '@ant-design/icons';
import { useAuditLog } from '../hooks';

const { Title, Text } = Typography;

const actionColor: Record<string, string> = {
  create_user: 'green', update_user: 'blue', delete_user: 'red',
  update_billing_threshold: 'orange', upload: 'cyan', check: 'geekblue',
};

const AuditLogTab: React.FC = () => {
  const { logs, total, loading, load } = useAuditLog();

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4}><AuditOutlined /> 操作审计 ({total})</Title>
        <Button icon={<ReloadOutlined />} onClick={load} size="small">刷新</Button>
      </div>
      <Table dataSource={logs} rowKey="id" loading={loading} size="small" pagination={{ pageSize: 30 }}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 60 },
          { title: '操作人', dataIndex: 'user_id', width: 80 },
          { title: '操作', dataIndex: 'action', width: 160,
            render: (v: string) => <Tag color={actionColor[v] || 'default'}>{v}</Tag> },
          { title: '资源', dataIndex: 'resource', width: 80 },
          { title: '资源ID', dataIndex: 'resource_id', width: 80 },
          { title: '详情', dataIndex: 'detail', ellipsis: true, width: 200,
            render: (v: string) => v ? <Text code style={{ fontSize: 11 }}>{v}</Text> : '-' },
          { title: '操作时间', dataIndex: 'created_at', width: 180,
            render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
        ]} />
    </div>
  );
};

export default AuditLogTab;
