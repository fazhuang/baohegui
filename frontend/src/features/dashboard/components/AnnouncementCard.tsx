/**
 * AnnouncementCard — 警示公告卡片
 *
 * 从 UserDashboard.tsx 拆分。
 */

import React from 'react';
import { Typography, Tag } from 'antd';

const { Text, Paragraph } = Typography;

export const SEVERITY_COLORS: Record<string, { border: string; bg: string; text: string; label: string }> = {
  critical: { border: '#dc2626', bg: '#fef2f2', text: '#991b1b', label: '严重' },
  danger: { border: '#ea580c', bg: '#fff7ed', text: '#9a3412', label: '高风险' },
  warning: { border: '#eab308', bg: '#fefce8', text: '#854d0e', label: '警示' },
  info: { border: '#2563eb', bg: '#eff6ff', text: '#1e40af', label: '信息' },
};

interface AnnouncementCardProps {
  id: number;
  title: string;
  severity: string;
  category: string;
  caseDate: string;
  summary: string;
  source: string;
}

const AnnouncementCard: React.FC<AnnouncementCardProps> = ({ title, severity, caseDate, summary, source }) => {
  const sc = SEVERITY_COLORS[severity] || SEVERITY_COLORS.info;
  return (
    <div style={{ padding: '12px 16px', borderLeft: `3px solid ${sc.border}`, background: sc.bg, borderRadius: '0 6px 6px 0', marginBottom: 10, cursor: 'pointer', transition: 'box-shadow 0.2s' }}
      onMouseEnter={e => { e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.06)'; }}
      onMouseLeave={e => { e.currentTarget.style.boxShadow = 'none'; }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0 }}>
          <Tag color={severity === 'critical' ? 'red' : severity === 'danger' ? 'orange' : severity === 'warning' ? 'gold' : 'blue'} style={{ margin: 0, fontSize: 11 }}>{sc.label}</Tag>
          <Text style={{ fontSize: 13, fontWeight: 600, flex: 1 }} ellipsis>{title}</Text>
        </div>
        <Text type="secondary" style={{ fontSize: 11, whiteSpace: 'nowrap', marginLeft: 8 }}>{caseDate}</Text>
      </div>
      <Paragraph type="secondary" style={{ fontSize: 12, lineHeight: 1.5, margin: 0 }} ellipsis={{ rows: 2 }}>{summary}</Paragraph>
      {source && <Text type="secondary" style={{ fontSize: 10, marginTop: 4, display: 'block' }}>来源：{source}</Text>}
    </div>
  );
};

export default AnnouncementCard;
