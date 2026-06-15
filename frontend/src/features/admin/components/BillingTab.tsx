/**
 * BillingTab — 计费与用量面板 Tab 组件
 *
 * 从 AdminPanel.tsx 拆分。
 */

import React from 'react';
import {
  Card, Typography, Row, Col, Statistic, Progress, Tag,
  Alert, Button, Space, InputNumber,
} from 'antd';
import {
  DollarOutlined, EditOutlined, CloseCircleOutlined, WarningOutlined,
} from '@ant-design/icons';
import { useBilling } from '../hooks';
import type { BillingStatus } from '../../../types';

const { Title, Text } = Typography;

const BillingTab: React.FC = () => {
  const { status, threshold, editingThreshold, saving, setThreshold, setEditingThreshold, handleSaveThreshold } = useBilling();
  const severityColor = (s: string) => s === 'critical' ? '#dc2626' : '#eab308';

  return (
    <div>
      <Title level={4}><DollarOutlined /> 计费与用量</Title>
      {(status?.alerts?.length ?? 0) > 0 && (
        <div style={{ marginBottom: 16 }}>
          {(status?.alerts ?? []).map((a: BillingStatus['alerts'][number], i: number) => (
            <Alert key={i} message={a.message} type={a.severity === 'critical' ? 'error' : 'warning'}
              showIcon icon={a.severity === 'critical' ? <CloseCircleOutlined /> : <WarningOutlined />}
              style={{ marginBottom: 8, borderRadius: 8, borderLeft: `4px solid ${severityColor(a.severity)}` }} />
          ))}
        </div>
      )}
      {status && (
        <Row gutter={16} style={{ marginBottom: 20 }}>
          <Col span={8}>
            <Card size="small">
              <Statistic title="Token 用量" value={status.tokens.used.toLocaleString()}
                suffix={<Text type="secondary">/ {status.tokens.limit.toLocaleString()}</Text>}
                valueStyle={{ color: status.tokens.pct >= 80 ? '#dc2626' : '#2563eb' }} />
              <Progress percent={status.tokens.pct} size="small" strokeLinecap="round"
                status={status.tokens.pct >= 100 ? 'exception' : 'active'}
                strokeColor={status.tokens.pct >= 80 ? 'var(--color-error)' : 'var(--color-action)'} />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Statistic title="费用 (元)" value={status.cost.used_yuan.toFixed(4)}
                suffix={<Text type="secondary">/ ¥{status.cost.limit_yuan}</Text>} precision={4}
                valueStyle={{ color: status.cost.pct >= 80 ? '#dc2626' : '#16a34a' }} />
              <Progress percent={status.cost.pct} size="small" strokeLinecap="round"
                status={status.cost.pct >= 100 ? 'exception' : 'active'}
                strokeColor={status.cost.pct >= 80 ? 'var(--color-error)' : 'var(--color-success)'} />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Statistic title="API 调用" value={status.calls.total}
                suffix={<Tag color={status.calls.success_rate >= 95 ? 'green' : 'gold'}>{status.calls.success_rate}% 成功</Tag>} />
              <Text type="secondary" style={{ fontSize: 12 }}>当前计费周期: {status.current_period}</Text>
            </Card>
          </Col>
        </Row>
      )}
      <Card size="small" title="用量阈值配置"
        extra={!editingThreshold
          ? <Button size="small" icon={<EditOutlined />} onClick={() => setEditingThreshold(true)}>修改</Button>
          : <Space>
            <Button size="small" onClick={() => setEditingThreshold(false)}>取消</Button>
            <Button size="small" type="primary" loading={saving} onClick={handleSaveThreshold}>保存</Button>
          </Space>
        } style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={8}><Text type="secondary">月 Token 上限</Text>
            <InputNumber value={threshold.max_monthly_tokens}
              onChange={(v) => setThreshold(prev => ({ ...prev, max_monthly_tokens: v || 0 }))}
              disabled={!editingThreshold} style={{ width: '100%' }}
              formatter={(v) => `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
              parser={(v) => Number((v || '').replace(/,/g, ''))} addonAfter="tokens" /></Col>
          <Col span={8}><Text type="secondary">月费用上限 (元)</Text>
            <InputNumber value={threshold.max_monthly_cost_yuan}
              onChange={(v) => setThreshold(prev => ({ ...prev, max_monthly_cost_yuan: v || 0 }))}
              disabled={!editingThreshold} style={{ width: '100%' }} min={0} step={10} addonAfter="¥" /></Col>
          <Col span={8}><Text type="secondary">告警阈值 (%)</Text>
            <InputNumber value={threshold.alert_threshold_pct}
              onChange={(v) => setThreshold(prev => ({ ...prev, alert_threshold_pct: v || 0 }))}
              disabled={!editingThreshold} style={{ width: '100%' }} min={10} max={100} step={5} addonAfter="%" /></Col>
        </Row>
        <Alert message="当用量或费用达到告警阈值时，系统将在管理中心顶部显示告警通知。" type="info" showIcon={false}
          style={{ marginTop: 12, background: '#f0f5ff', border: 'none', fontSize: 11, borderRadius: 6 }} />
      </Card>
    </div>
  );
};

export default BillingTab;
