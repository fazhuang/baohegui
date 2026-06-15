/**
 * QuickAction — 快速操作入口卡片
 *
 * 从 UserDashboard.tsx 拆分。
 */

import React from 'react';
import { Typography } from 'antd';
import { ArrowRightOutlined } from '@ant-design/icons';

const { Text } = Typography;

interface QuickActionProps {
  icon: React.ReactNode;
  label: string;
  description: string;
  onClick: () => void;
  primary?: boolean;
}

const QuickAction: React.FC<QuickActionProps> = ({ icon, label, description, onClick, primary }) => (
  <div onClick={onClick} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '14px 18px', borderRadius: 10, border: primary ? '1px solid #2563eb' : '1px solid #e2e8f0', background: primary ? '#eff6ff' : '#fff', cursor: 'pointer', transition: 'all 0.2s' }}
    onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)'; }}
    onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = 'none'; }}>
    <div style={{ width: 42, height: 42, borderRadius: 10, background: primary ? '#2563eb' : '#eff6ff', display: 'flex', alignItems: 'center', justifyContent: 'center', color: primary ? '#fff' : '#2563eb', fontSize: 20 }}>{icon}</div>
    <div style={{ flex: 1 }}><Text strong style={{ fontSize: 14 }}>{label}</Text><br /><Text type="secondary" style={{ fontSize: 12 }}>{description}</Text></div>
    <ArrowRightOutlined style={{ color: '#94a3b8', fontSize: 14 }} />
  </div>
);

export default QuickAction;
