/**
 * RulesEditorToolbar — 规则编辑器搜索 + 批量操作工具栏
 *
 * 从 RulesEditor.tsx 拆分。
 */

import React from 'react';
import { Card, Input, Button, Typography, Space, Popconfirm } from 'antd';
import { SearchOutlined, CheckOutlined, CloseOutlined, ExclamationCircleOutlined } from '@ant-design/icons';

const { Text } = Typography;

interface RulesEditorToolbarProps {
  search: string;
  selectedCount: number;
  batchLoading: boolean;
  onSearchChange: (v: string) => void;
  onBatchToggle: (enabled: boolean) => void;
}

const RulesEditorToolbar: React.FC<RulesEditorToolbarProps> = ({
  search, selectedCount, batchLoading, onSearchChange, onBatchToggle,
}) => (
  <Card size="small" style={{ marginBottom: 16, borderRadius: 10 }}>
    <Space wrap size="middle">
      <Input
        prefix={<SearchOutlined />}
        placeholder="搜索规则 ID / 描述 / 平台..."
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
        style={{ width: 280 }}
        allowClear
      />
      <Popconfirm
        title={`确认启用 ${selectedCount} 条规则？`}
        icon={<ExclamationCircleOutlined style={{ color: '#16a34a' }} />}
        onConfirm={() => onBatchToggle(true)}
        okText="确认启用"
        cancelText="取消"
      >
        <Button icon={<CheckOutlined />} type="primary" disabled={selectedCount === 0} loading={batchLoading}>
          批量启用 ({selectedCount})
        </Button>
      </Popconfirm>
      <Popconfirm
        title={`确认停用 ${selectedCount} 条规则？`}
        icon={<ExclamationCircleOutlined style={{ color: '#dc2626' }} />}
        onConfirm={() => onBatchToggle(false)}
        okText="确认停用"
        okButtonProps={{ danger: true }}
        cancelText="取消"
      >
        <Button icon={<CloseOutlined />} danger disabled={selectedCount === 0} loading={batchLoading}>
          批量停用 ({selectedCount})
        </Button>
      </Popconfirm>
      {selectedCount > 0 && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          已选择 {selectedCount} 条规则
        </Text>
      )}
    </Space>
  </Card>
);

export default RulesEditorToolbar;
