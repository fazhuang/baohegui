/**
 * KpiCard — Dashboard KPI 统计卡片
 *
 * 使用方式:
 *   <KpiCard title="今日审查" value={47} suffix="次" icon={<FileSearchOutlined />}
 *            color="#1677ff" trend={{ value: 12, isUp: true }} loading={false} />
 */

import React from 'react';
import { Card, Typography, Skeleton } from 'antd';
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons';

const { Text } = Typography;

interface KpiCardProps {
  title: string;
  value: number | string;
  icon: React.ReactNode;
  color: string;
  bgColor?: string;
  suffix?: string;
  loading?: boolean;
  trend?: {
    value: number;
    isUp: boolean;
    label?: string;
  };
  onClick?: () => void;
}

const KpiCard: React.FC<KpiCardProps> = ({
  title, value, icon, color, bgColor, suffix, loading, trend, onClick,
}) => (
  <Card
    style={{
      borderRadius: 12,
      border: '1px solid #f0f0f0',
      height: '100%',
      cursor: onClick ? 'pointer' : 'default',
    }}
    styles={{ body: { padding: '20px 24px' } }}
    onClick={onClick}
  >
    {loading ? (
      <Skeleton active paragraph={{ rows: 1 }} />
    ) : (
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <Text type="secondary" style={{ fontSize: 13 }}>{title}</Text>
          <div style={{ marginTop: 4, display: 'flex', alignItems: 'baseline', gap: 4 }}>
            <span style={{ fontSize: 28, fontWeight: 700, color: '#1e293b', lineHeight: 1 }}>
              {value}
            </span>
            {suffix && <Text type="secondary" style={{ fontSize: 14 }}>{suffix}</Text>}
          </div>
          {trend && (
            <div style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
              {trend.isUp ? (
                <ArrowUpOutlined style={{ color: '#dc2626', fontSize: 12 }} />
              ) : (
                <ArrowDownOutlined style={{ color: '#16a34a', fontSize: 12 }} />
              )}
              <Text
                style={{
                  fontSize: 12,
                  color: trend.isUp ? '#dc2626' : '#16a34a',
                }}
              >
                {trend.value}% {trend.label ?? (trend.isUp ? '上升' : '下降')}
              </Text>
            </div>
          )}
        </div>
        <div
          style={{
            width: 44, height: 44, borderRadius: 10,
            background: bgColor ?? `${color}15`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color,
            fontSize: 22,
          }}
        >
          {icon}
        </div>
      </div>
    )}
  </Card>
);

export default KpiCard;
