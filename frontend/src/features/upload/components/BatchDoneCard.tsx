/**
 * BatchDoneCard — 批量完成结果卡片
 *
 * 从 Upload.tsx 拆分。
 */

import React from 'react';
import { Card, Typography, Button, Space, Tag } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, ArrowRightOutlined, ReloadOutlined } from '@ant-design/icons';
import type { FileItemData } from '../types';

const { Title, Text } = Typography;

interface BatchDoneCardProps {
  files: FileItemData[];
  onNavigateReport: (id: number) => void;
  onRetryFile: (id: number) => void;
  onReset: () => void;
}

const BatchDoneCard: React.FC<BatchDoneCardProps> = ({ files, onNavigateReport, onRetryFile, onReset }) => (
  <Card style={{ borderRadius: 12, marginBottom: 20 }} styles={{ body: { padding: '24px 20px', textAlign: 'center' } }}>
    <CheckCircleOutlined style={{ fontSize: 48, color: 'var(--color-success)', marginBottom: 12 }} />
    <Title level={4} style={{ marginBottom: 4 }}>全部检查完成</Title>
    <Text type="secondary" style={{ display: 'block', marginBottom: 20 }}>已完成 {files.filter(f => f.status === 'done').length}/{files.length} 份文件的合规审查</Text>
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 500, margin: '0 auto 20px auto', textAlign: 'left' }}>
      {files.map((item) => (
        <div key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8,
          background: item.status === 'done' ? 'var(--color-bg)' : '#fff2f0', border: '1px solid var(--color-border)' }}>
          {item.status === 'done' ? <CheckCircleOutlined style={{ color: 'var(--color-success)', fontSize: 16 }} /> : <CloseCircleOutlined style={{ color: 'var(--color-error)', fontSize: 16 }} />}
          <div style={{ flex: 1, minWidth: 0 }}>
            <Text style={{ fontSize: 13, display: 'block' }} ellipsis>{item.file.name}</Text>
            {item.status === 'done' && item.result && <Tag color={item.result.score >= 85 ? 'green' : item.result.score >= 60 ? 'gold' : 'red'} style={{ marginTop: 2, fontSize: 11 }}>评分 {item.result.score}</Tag>}
            {item.status === 'error' && <Text type="danger" style={{ fontSize: 11, display: 'block' }}>{item.errorMsg || '处理失败'}</Text>}
          </div>
          {item.status === 'done' && item.result && <Button size="small" type="primary" ghost icon={<ArrowRightOutlined />} onClick={() => onNavigateReport(item.result!.report_id)}>查看报告</Button>}
          {item.status === 'error' && <Button size="small" type="link" icon={<ReloadOutlined />} onClick={() => onRetryFile(item.id)}>重试</Button>}
        </div>
      ))}
    </div>
    <Space><Button type="primary" size="large" onClick={onReset} style={{ borderRadius: 8, paddingLeft: 28, paddingRight: 28 }}>检查新文件</Button></Space>
  </Card>
);

export default BatchDoneCard;
