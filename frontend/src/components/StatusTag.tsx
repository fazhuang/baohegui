/**
 * StatusTag — 统一状态/风险等级标签
 *
 * 使用方式:
 *   <StatusTag riskLevel="high" />
 *   <StatusTag status="completed" />
 */

import React from 'react';
import { Tag } from 'antd';

type RiskLevel = 'critical' | 'high' | 'medium' | 'low' | 'pass';
type StatusType = 'completed' | 'failed' | 'checking' | 'uploaded' | 'queued' | 'pending';

const RISK_CONFIG: Record<string, { color: string; label: string }> = {
  critical: { color: 'red', label: '严重' },
  high: { color: 'orange', label: '高风险' },
  medium: { color: 'gold', label: '中风险' },
  low: { color: 'green', label: '低风险' },
  pass: { color: 'blue', label: '通过' },
};

const STATUS_CONFIG: Record<string, { color: string; label: string }> = {
  completed: { color: 'green', label: '已完成' },
  failed: { color: 'red', label: '失败' },
  checking: { color: 'processing', label: '审查中' },
  uploaded: { color: 'blue', label: '已上传' },
  queued: { color: 'default', label: '排队中' },
  pending: { color: 'default', label: '待处理' },
};

interface StatusTagProps {
  riskLevel?: RiskLevel | string;
  status?: StatusType | string;
  style?: React.CSSProperties;
}

const StatusTag: React.FC<StatusTagProps> = ({ riskLevel, status, style }) => {
  if (riskLevel) {
    const cfg = RISK_CONFIG[riskLevel] ?? { color: 'default', label: riskLevel };
    return <Tag color={cfg.color} style={{ ...style, margin: 0 }}>{cfg.label}</Tag>;
  }
  if (status) {
    const cfg = STATUS_CONFIG[status] ?? { color: 'default', label: status };
    return <Tag color={cfg.color} style={{ ...style, margin: 0 }}>{cfg.label}</Tag>;
  }
  return null;
};

export default StatusTag;
