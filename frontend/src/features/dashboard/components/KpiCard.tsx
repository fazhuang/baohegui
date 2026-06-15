/**
 * KpiCard — 仪表盘 KPI 卡片
 *
 * 从 UserDashboard.tsx 拆分。
 */

import React from 'react';
import { Card, Typography, Skeleton } from 'antd';

const { Text } = Typography;

interface KpiCardProps {
  title: string;
  value: number | string;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
  suffix?: string;
  loading: boolean;
}

const KpiCard: React.FC<KpiCardProps> = ({ title, value, icon, color, bgColor, suffix, loading }) => (
  <Card style={{ borderRadius: 12, border: '1px solid #e2e8f0', height: '100%' }} styles={{ body: { padding: '20px 24px' } }}>
    {loading ? <Skeleton active paragraph={{ rows: 1 }} /> : (
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <Text type="secondary" style={{ fontSize: 13 }}>{title}</Text>
          <div style={{ marginTop: 4, display: 'flex', alignItems: 'baseline', gap: 4 }}>
            <span style={{ fontSize: 28, fontWeight: 700, color: '#334155', lineHeight: 1 }}>{value}</span>
            {suffix && <Text type="secondary" style={{ fontSize: 14 }}>{suffix}</Text>}
          </div>
        </div>
        <div style={{ width: 44, height: 44, borderRadius: 10, background: bgColor, display: 'flex', alignItems: 'center', justifyContent: 'center', color, fontSize: 22 }}>{icon}</div>
      </div>
    )}
  </Card>
);

export default KpiCard;
