/**
 * RiskDistribution — 风险等级分布条
 *
 * 使用方式:
 *   <RiskDistribution items={[{ label: '高风险', count: 3, color: '#dc2626' }, ...]} />
 */

import React from 'react';
import { Typography } from 'antd';

const { Text } = Typography;

interface RiskItem {
  label: string;
  count: number;
  color: string;
}

interface RiskDistributionProps {
  items: RiskItem[];
  total?: number;
}

const RiskDistribution: React.FC<RiskDistributionProps> = ({ items, total }) => {
  const t = total ?? items.reduce((s, i) => s + i.count, 0);

  return (
    <div>
      {items.map(item => {
        const pct = t > 0 ? Math.round((item.count / t) * 100) : 0;
        return (
          <div key={item.label} style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{ width: 10, height: 10, borderRadius: 3, background: item.color }} />
                <Text style={{ fontSize: 13 }}>{item.label}</Text>
              </div>
              <Text strong style={{ fontSize: 14 }}>{item.count}</Text>
            </div>
            <div style={{ height: 6, borderRadius: 3, background: '#f1f5f9', overflow: 'hidden' }}>
              <div
                style={{
                  height: '100%',
                  width: `${pct}%`,
                  background: item.color,
                  borderRadius: 3,
                  transition: 'width 0.6s ease',
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default RiskDistribution;
