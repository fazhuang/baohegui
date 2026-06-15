/**
 * PassRateRing — 通过率环形图
 *
 * 从 UserDashboard.tsx 拆分。
 */

import React from 'react';
import { Typography } from 'antd';

const { Text } = Typography;

interface PassRateRingProps {
  rate: number;
}

const PassRateRing: React.FC<PassRateRingProps> = ({ rate }) => {
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (rate / 100) * circumference;
  const isHigh = rate >= 80;
  return (
    <div style={{ position: 'relative', width: 90, height: 90, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <svg width="90" height="90" viewBox="0 0 90 90" style={{ position: 'absolute' }}>
        <circle cx="45" cy="45" r={radius} fill="none" stroke="#e2e8f0" strokeWidth="8" />
        <circle cx="45" cy="45" r={radius} fill="none"
          stroke={isHigh ? '#16a34a' : '#eab308'} strokeWidth="8" strokeLinecap="round"
          strokeDasharray={circumference} strokeDashoffset={offset}
          transform="rotate(-90 45 45)" style={{ transition: 'stroke-dashoffset 0.8s ease' }} />
      </svg>
      <Text strong style={{ fontSize: 18, color: isHigh ? '#16a34a' : '#eab308' }}>{rate}%</Text>
    </div>
  );
};

export default PassRateRing;
