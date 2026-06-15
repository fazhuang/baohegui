/** Report feature — 可视化组件 (雷达图 / 评分圆环 / 评分条 / 引用块) */

import React from 'react';
import { Progress, Space, Typography } from 'antd';
import { getScoreColor } from '../utils';

const { Text } = Typography;

// ═══════════════════════════════════════════════════════════════
// SVG 雷达图
// ═══════════════════════════════════════════════════════════════

export const RadarChart: React.FC<{
  scores: { label: string; value: number }[];
  size?: number;
}> = ({ scores, size = 240 }) => {
  const cx = size / 2;
  const cy = size / 2;
  const r = size * 0.38;
  const levels = [25, 50, 75, 100];
  const angles = scores.map((_, i) => (i * 2 * Math.PI) / scores.length - Math.PI / 2);

  const gridPoints = (level: number) =>
    angles.map(a => ({
      x: cx + (r * level) / 100 * Math.cos(a),
      y: cy + (r * level) / 100 * Math.sin(a),
    }));

  const dataPoints = scores.map((s, i) => ({
    x: cx + (r * s.value) / 100 * Math.cos(angles[i]),
    y: cy + (r * s.value) / 100 * Math.sin(angles[i]),
  }));

  const polyStr = dataPoints.map(p => `${p.x},${p.y}`).join(' ');

  return (
    <svg width={size} height={size} style={{ display: 'block', margin: '0 auto' }}>
      {levels.map(lv => {
        const pts = gridPoints(lv);
        return (
          <polygon
            key={lv}
            points={pts.map(p => `${p.x},${p.y}`).join(' ')}
            fill="none" stroke="var(--color-border)" strokeWidth={1}
            strokeDasharray={lv === 100 ? 'none' : '4,2'}
          />
        );
      })}
      {angles.map((a, i) => (
        <line key={i} x1={cx} y1={cy} x2={cx + r * Math.cos(a)} y2={cy + r * Math.sin(a)} stroke="var(--color-border)" strokeWidth={1} />
      ))}
      <polygon points={polyStr} fill="rgba(37, 99, 235, 0.12)" stroke="var(--color-action)" strokeWidth={2} />
      {dataPoints.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={4} fill="var(--color-action)" stroke="#fff" strokeWidth={2} />
      ))}
      {scores.map((s, i) => {
        const labelR = r * 1.25;
        const lx = cx + labelR * Math.cos(angles[i]);
        const ly = cy + labelR * Math.sin(angles[i]);
        const anchor = Math.abs(angles[i]) < 0.1 ? 'middle' : angles[i] > 0 && angles[i] < Math.PI ? 'start' : 'end';
        return (
          <g key={i}>
            <text x={lx} y={ly - 8} textAnchor={anchor} fontSize={11} fill="var(--color-text-secondary)">{s.label}</text>
            <text x={lx} y={ly + 8} textAnchor={anchor} fontSize={13} fontWeight="bold" fill={getScoreColor(s.value)}>{s.value}</text>
          </g>
        );
      })}
    </svg>
  );
};

// ═══════════════════════════════════════════════════════════════
// 评分圆环 (SVG)
// ═══════════════════════════════════════════════════════════════

export const ScoreRing: React.FC<{ score: number; size?: number }> = ({ score, size = 120 }) => {
  const color = getScoreColor(score);
  const sw = 8;
  const radius = (size - sw) / 2;
  const circum = 2 * Math.PI * radius;
  const offset = circum - (score / 100) * circum;
  return (
    <div style={{ position: 'relative', width: size, height: size, margin: '0 auto' }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--color-border)" strokeWidth={sw} />
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={color} strokeWidth={sw}
          strokeDasharray={circum} strokeDashoffset={offset} strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dashoffset 1s ease-in-out' }} />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <Text style={{ fontSize: 28, fontWeight: 'bold', color, lineHeight: 1 }}>{score}</Text>
        <Text style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginTop: 2 }}>合规评分</Text>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════
// 评分条 (compact)
// ═══════════════════════════════════════════════════════════════

export const ScoreBar: React.FC<{ label: string; value: number; icon: React.ReactNode }> = ({ label, value, icon }) => (
  <div style={{ marginBottom: 10 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
      <Space size={4}>{icon}<Text style={{ fontSize: 12 }}>{label}</Text></Space>
      <Text strong style={{ color: getScoreColor(value), fontSize: 13 }}>{value}</Text>
    </div>
    <Progress percent={value} size="small" strokeColor={getScoreColor(value)} trailColor="var(--color-bg)" showInfo={false} />
  </div>
);

// ═══════════════════════════════════════════════════════════════
// 引用文本块
// ═══════════════════════════════════════════════════════════════

export const QuoteBlock: React.FC<{ text: string }> = ({ text }) => (
  <div style={{
    background: 'var(--color-bg)', borderLeft: '3px solid var(--color-border)',
    padding: '8px 12px', margin: '6px 0', borderRadius: '0 4px 4px 0',
    fontFamily: 'SF Mono, Monaco, monospace', fontSize: 12, color: 'var(--color-text)',
    whiteSpace: 'pre-wrap', wordBreak: 'break-all',
  }}>
    {text.length > 200 ? text.slice(0, 200) + '…' : text}
  </div>
);
