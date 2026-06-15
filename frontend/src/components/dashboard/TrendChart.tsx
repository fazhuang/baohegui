/**
 * TrendChart — Dashboard 迷你趋势柱状图
 *
 * 使用方式:
 *   <TrendChart data={[{ month: '01', count: 12 }, ...]} />
 */

import React from 'react';
import { Tooltip, Typography } from 'antd';

const { Text } = Typography;

interface TrendDataPoint {
  label: string;
  count: number;
}

interface TrendChartProps {
  data: TrendDataPoint[];
  height?: number;
}

const TrendChart: React.FC<TrendChartProps> = ({ data, height = 40 }) => {
  const max = Math.max(...data.map(d => d.count), 1);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height, paddingTop: 4 }}>
        {data.map((d, i) => (
          <Tooltip key={i} title={`${d.label}: ${d.count} 次`}>
            <div
              style={{
                flex: 1,
                height: `${Math.max((d.count / max) * 100, 4)}%`,
                background: d.count > 0 ? '#1677ff' : '#e2e8f0',
                borderRadius: '3px 3px 0 0',
                transition: 'height 0.3s ease',
                cursor: 'pointer',
                minHeight: 4,
              }}
            />
          </Tooltip>
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
        {data.map((d, i) => (
          <Text key={i} type="secondary" style={{ fontSize: 10, flex: 1, textAlign: 'center' }}>
            {d.label}
          </Text>
        ))}
      </div>
    </div>
  );
};

export default TrendChart;
