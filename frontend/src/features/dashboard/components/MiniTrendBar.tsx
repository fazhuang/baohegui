/**
 * MiniTrendBar — 迷你趋势柱状图
 *
 * 从 UserDashboard.tsx 拆分。
 */

import React from 'react';
import { Tooltip } from 'antd';

interface MiniTrendBarProps {
  data: Array<{ month: string; count: number }>;
}

const MiniTrendBar: React.FC<MiniTrendBarProps> = ({ data }) => {
  const max = Math.max(...data.map(d => d.count), 1);
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 40, paddingTop: 4 }}>
      {data.map((d, i) => (
        <Tooltip key={i} title={`${d.month}: ${d.count} 次`}>
          <div style={{
            width: 12, height: `${Math.max((d.count / max) * 100, 4)}%`,
            background: d.count > 0 ? '#1677ff' : '#e2e8f0',
            borderRadius: '3px 3px 0 0', transition: 'height 0.3s ease',
            cursor: 'pointer', minHeight: 4,
          }} />
        </Tooltip>
      ))}
    </div>
  );
};

export default MiniTrendBar;
