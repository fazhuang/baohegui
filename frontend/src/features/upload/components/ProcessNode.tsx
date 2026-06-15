/** Upload feature — 通用组件 */

import React from 'react';
import { Progress, Typography, Button } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, ReloadOutlined } from '@ant-design/icons';
import type { StepConfig } from '../types';

const { Text } = Typography;

/** 过程轨道单节点 */
export const ProcessNode: React.FC<{
  step: StepConfig;
  status: 'wait' | 'active' | 'done' | 'error';
  errorMsg?: string;
  onRetry?: () => void;
  progressPct?: number;
}> = ({ step, status, errorMsg, onRetry, progressPct = 0 }) => {
  const circleClass = [
    'process-node-circle',
    status === 'active' ? 'active' : '',
    status === 'done' ? 'done' : '',
    status === 'error' ? 'error' : '',
  ].filter(Boolean).join(' ');

  const labelClass = [
    'process-node-label',
    status === 'active' ? 'active' : '',
    status === 'done' ? 'done' : '',
    status === 'error' ? 'error' : '',
  ].join(' ');

  return (
    <div className="process-node" style={{ minWidth: 80 }}>
      <div className={circleClass}>
        {status === 'done' ? <CheckCircleOutlined /> : status === 'error' ? <CloseCircleOutlined /> : step.icon}
      </div>
      <div className={labelClass} style={{ fontWeight: status === 'active' ? 600 : 400, fontSize: 13 }}>
        {step.label}
      </div>
      {status === 'active' && (
        <Progress percent={Math.min(progressPct, 95)} size="small"
          strokeColor="var(--color-action)" trailColor="var(--color-brand-light)"
          style={{ width: 100, marginTop: 4 }} showInfo={false} />
      )}
      {status === 'active' && (
        <Text type="secondary" style={{ fontSize: 11 }}>{step.subtitle}</Text>
      )}
      {status === 'error' && errorMsg && (
        <div style={{ marginTop: 4, textAlign: 'center' }}>
          <Text type="danger" style={{ fontSize: 11 }}>{errorMsg}</Text>
          {onRetry && (
            <div style={{ marginTop: 4 }}>
              <Button size="small" type="link" danger icon={<ReloadOutlined />} onClick={onRetry}>重试</Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
