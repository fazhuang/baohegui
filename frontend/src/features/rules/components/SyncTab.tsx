/**
 * SyncTab — 同步管理 Tab 视图
 *
 * 从 AdminRules.tsx 拆分到 features/rules/components。
 */

import React from 'react';
import { Card, Table, Tag, Button, Typography, Space, Tooltip } from 'antd';
import { SyncOutlined } from '@ant-design/icons';
import { useSyncManager } from '../hooks';

const { Text } = Typography;

const SyncTab: React.FC = () => {
  const { status, history, syncing, handleSync } = useSyncManager();

  const statusColor = (s: string) =>
    s === 'success' ? 'green' : s === 'failed' ? 'red' : s === 'running' ? 'blue' : 'default';

  return (
    <div>
      <Card title="同步状态" style={{ marginBottom: 16 }}>
        {status && (
          <Space direction="vertical" size={8}>
            <Text>引擎规则: <strong>{status.rule_engine_loaded}</strong> 条</Text>
            <Text>平台规则: <strong>{status.total_rules}</strong> 条 (启用 {status.enabled_rules})</Text>
            <Text>可用平台: {status.available_platforms?.join('、')}</Text>
            {status.last_sync && (
              <Text type="secondary">上次同步: {status.last_sync.platform} · {status.last_sync.time} · {status.last_sync.status}</Text>
            )}
          </Space>
        )}
      </Card>
      <Card title="立即同步" style={{ marginBottom: 16 }}>
        <Space wrap>
          {(status?.available_platforms || ['广东省公共资源交易平台']).map(p => (
            <Button key={p} icon={<SyncOutlined />} loading={syncing} onClick={() => handleSync(p)} disabled={syncing}>
              同步 {p}
            </Button>
          ))}
        </Space>
      </Card>
      <Card title="同步历史">
        <Table dataSource={history} rowKey="id" size="small" pagination={{ pageSize: 10 }}
          columns={[
            { title: '平台', dataIndex: 'platform', key: 'platform', width: 160 },
            { title: '状态', dataIndex: 'status', key: 'status', width: 80,
              render: (v: string) => <Tag color={statusColor(v)}>{v}</Tag> },
            { title: '新增', dataIndex: 'new_rules', key: 'new_rules', width: 60 },
            { title: '更新', dataIndex: 'updated_rules', key: 'updated_rules', width: 60 },
            { title: '重试', dataIndex: 'retry_count', key: 'retry_count', width: 60 },
            { title: '版本', dataIndex: 'version', key: 'version', width: 80 },
            { title: '时间', dataIndex: 'finished_at', key: 'finished_at', width: 160 },
            { title: '错误', dataIndex: 'errors', key: 'errors',
              render: (e: string[]) => e?.length
                ? <Tooltip title={e.join('; ')}><Tag color="red">{e.length} 个</Tag></Tooltip> : '-' },
          ]} />
      </Card>
    </div>
  );
};

export default SyncTab;
