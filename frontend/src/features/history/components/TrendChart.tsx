/**
 * TrendChart — SVG 合规评分趋势图
 *
 * 从 History.tsx 拆分到 features/history/components。
 */

import React from 'react';
import type { ReportListItem } from '../../../types';

const W = 640;
const H = 180;
const PX = 44;
const PY = 24;
const MAX_SCORE = 100;

interface TrendChartProps {
  reports: ReportListItem[];
}

const TrendChart: React.FC<TrendChartProps> = ({ reports }) => {
  const xStep = (W - PX - 24) / Math.max(reports.length - 1, 1);
  const pts = reports.map((r, i) => ({
    x: PX + i * xStep,
    y: H - PY - (r.total_score / MAX_SCORE) * (H - 2 * PY),
    score: r.total_score,
    label: `#${r.id}`,
  }));
  const line = pts.map((p) => `${p.x},${p.y}`).join(' ');
  const areaPath = `${pts[0].x},${H - PY} ${line} ${pts[pts.length - 1].x},${H - PY}`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxHeight: H, marginTop: 8 }}>
      {[0, 25, 50, 75, 100].map((value) => {
        const y = H - PY - (value / MAX_SCORE) * (H - 2 * PY);
        return (
          <g key={value}>
            <line x1={PX} y1={y} x2={W - 12} y2={y} stroke="var(--color-border)" strokeWidth={1} />
            <text x={PX - 8} y={y + 4} textAnchor="end" fontSize={10} fill="var(--color-text-tertiary)">{value}</text>
          </g>
        );
      })}
      <polygon points={areaPath} fill="rgba(37,99,235,0.08)" />
      <polyline points={line} fill="none" stroke="var(--color-action)" strokeWidth={2} strokeLinejoin="round" />
      {pts.map((point, index) => (
        <g key={index}>
          <circle cx={point.x} cy={point.y} r={4} fill="var(--color-action)" stroke="#fff" strokeWidth={2} />
          <text x={point.x} y={point.y - 10} textAnchor="middle" fontSize={10} fill="var(--color-text-secondary)">{point.score}</text>
        </g>
      ))}
      {pts.map((point, idx) => (
        <text key={idx} x={point.x} y={H - 4} textAnchor="middle" fontSize={9} fill="var(--color-text-tertiary)">{point.label}</text>
      ))}
    </svg>
  );
};

export default TrendChart;
