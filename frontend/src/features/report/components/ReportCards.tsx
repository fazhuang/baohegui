/** Report feature — 优先级卡片 + 风险热力图 + 管线摘要 */

import React, { useMemo } from 'react';
import { Card, Tag, Space, Typography, Row, Col, Descriptions, Alert } from 'antd';
import {
  FlagOutlined, BranchesOutlined, AimOutlined,
  SafetyCertificateOutlined, ThunderboltOutlined, HeatMapOutlined,
} from '@ant-design/icons';
import type { RuleViolation, LLMViolation } from '../../../types';
import { getRiskTag, getRiskColor, extractSectionName, type PipelineSummaryData } from '../utils';

const { Text } = Typography;

// ═══════════════════════════════════════════════════════════════
// 整改优先级卡片
// ═══════════════════════════════════════════════════════════════

export const PriorityCard: React.FC<{
  violations: RuleViolation[];
  llmViolations: LLMViolation[];
}> = ({ violations, llmViolations }) => {
  const all = useMemo(() => {
    const rules = violations.map(v => ({
      key: v.rule_id, risk: v.risk_level, weight: v.weight,
      desc: v.description, suggestion: v.suggestion, law_ref: v.law_ref, source: 'rule' as const,
    }));
    const llms = llmViolations.map((v, i) => ({
      key: `llm-${i}`, risk: v.risk_level, weight: v.weight,
      desc: v.reason, suggestion: v.suggestion, law_ref: v.law_ref, source: 'llm' as const,
    }));
    const order: Record<string, number> = { high: 0, medium: 1, low: 2 };
    return [...rules, ...llms]
      .sort((a, b) => order[a.risk] - order[b.risk] || b.weight - a.weight)
      .slice(0, 5);
  }, [violations, llmViolations]);

  if (all.length === 0) return null;

  return (
    <Card
      title={<Space><FlagOutlined style={{ color: 'var(--color-error)' }} /><span>优先整改建议</span><Tag color="red">前 {all.length} 项</Tag></Space>}
      className="card-accent-red" style={{ marginBottom: 20, borderRadius: 12 }}
    >
      {all.map((item, i) => (
        <div key={item.key} style={{ marginBottom: i < all.length - 1 ? 10 : 0 }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
            <span style={{ fontSize: 24, fontWeight: 700, color: '#e2e8f0', lineHeight: 1, minWidth: 36, textAlign: 'right' }}>#{i + 1}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Space size={[4, 4]} wrap style={{ marginBottom: 4 }}>
                {getRiskTag(item.risk)}
                {item.source === 'rule' ? <Tag>规则引擎</Tag> : <Tag color="cyan">AI语义</Tag>}
              </Space>
              <Text style={{ fontSize: 13, display: 'block', marginBottom: 2 }}>{item.desc}</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>{item.suggestion}</Text>
              {item.law_ref && <div><Tag color="blue" style={{ fontSize: 10 }}>{item.law_ref}</Tag></div>}
            </div>
          </div>
          {i < all.length - 1 && <div style={{ borderBottom: '1px solid #f0f0f0', marginTop: 8, marginBottom: 8 }} />}
        </div>
      ))}
    </Card>
  );
};

// ═══════════════════════════════════════════════════════════════
// 风险热力图
// ═══════════════════════════════════════════════════════════════

export const RiskHeatmap: React.FC<{
  violations: RuleViolation[];
  llmViolations: LLMViolation[];
}> = ({ violations, llmViolations }) => {
  const sections = useMemo(() => {
    const map: Record<string, { rule_high: number; rule_medium: number; rule_low: number; llm_high: number; llm_medium: number; llm_low: number }> = {};
    const init = () => ({ rule_high: 0, rule_medium: 0, rule_low: 0, llm_high: 0, llm_medium: 0, llm_low: 0 });
    violations.forEach(v => {
      const s = extractSectionName(v.location || '');
      if (!map[s]) map[s] = init();
      map[s][`rule_${v.risk_level}` as keyof ReturnType<typeof init>]++;
    });
    llmViolations.forEach(v => {
      const s = extractSectionName(v.section || '');
      if (!map[s]) map[s] = init();
      map[s][`llm_${v.risk_level}` as keyof ReturnType<typeof init>]++;
    });
    return Object.entries(map).sort(([, a], [, b]) =>
      (b.rule_high + b.llm_high) - (a.rule_high + a.llm_high));
  }, [violations, llmViolations]);

  if (sections.length === 0) return null;

  return (
    <Card title={<Space><HeatMapOutlined /><span>风险热力图</span></Space>} style={{ marginBottom: 20, borderRadius: 12 }}>
      {sections.map(([section, counts]) => (
        <div key={section} style={{ marginBottom: 10 }}>
          <Text style={{ fontSize: 12, marginBottom: 4, display: 'block' }}>{section}</Text>
          <div style={{ display: 'flex', gap: 4, height: 8 }}>
            {['rule', 'llm'].map(source => ['high', 'medium', 'low'].map(level => {
              const count = counts[`${source}_${level}` as keyof typeof counts] as number;
              const max = Math.max(...Object.values(counts)) || 1;
              const width = `${Math.max((count / max) * 100, count > 0 ? 4 : 0)}%`;
              return count > 0 ? (
                <div key={`${source}-${level}`} title={`${source} ${level}: ${count}`}
                  style={{ width, height: '100%', background: getRiskColor(level), borderRadius: 2, opacity: source === 'rule' ? 1 : 0.5, transition: 'width 0.3s' }} />
              ) : null;
            }))}
          </div>
        </div>
      ))}
    </Card>
  );
};

// ═══════════════════════════════════════════════════════════════
// 五层审查管线摘要
// ═══════════════════════════════════════════════════════════════

export const PipelineSummary: React.FC<{ data: PipelineSummaryData; isMobile: boolean }> = ({ data, isMobile }) => {
  const riskLabel: Record<string, string> = {
    low: '✅ 低风险通过', medium: '⚠️ 中等风险需关注', high: '🔴 高风险需整改', critical: '🚨 严重违规',
  };
  const statusLabel: Record<string, string> = {
    auto_passed: '✅ 自动通过', auto_failed: '❌ 自动拒绝', needs_review: '⏳ 待人工复核',
    reviewed_passed: '✅ 复核通过', reviewed_failed: '❌ 复核拒绝',
  };

  return (
    <Card title={<Space><BranchesOutlined /><span>五层审查管线</span></Space>} style={{ marginBottom: 20, borderRadius: 12 }}>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={isMobile ? 24 : 8}>
          <div style={{ padding: 12, borderRadius: 8, background: '#f8fafc', textAlign: 'center' }}>
            <SafetyCertificateOutlined style={{ fontSize: 24, marginBottom: 6, color: 'var(--color-action)' }} />
            <Text strong style={{ display: 'block', fontSize: 13 }}>路由判定</Text>
            <Text style={{ color: data.traffic_light === 'red' ? '#dc2626' : data.traffic_light === 'yellow' ? '#eab308' : '#16a34a', fontSize: 12 }}>
              {data.traffic_light === 'red' ? '🔴' : data.traffic_light === 'yellow' ? '🟡' : '🟢'} {data.traffic_light || '未知'}
            </Text>
          </div>
        </Col>
        <Col xs={24} sm={isMobile ? 24 : 8}>
          <div style={{ padding: 12, borderRadius: 8, background: '#f8fafc', textAlign: 'center' }}>
            <AimOutlined style={{ fontSize: 24, marginBottom: 6, color: '#7c3aed' }} />
            <Text strong style={{ display: 'block', fontSize: 13 }}>参数倾向性</Text>
            <Text style={{ fontSize: 12 }}>评分 {data.parameter_bias_score ?? '-'} · 发现 {data.parameter_bias_findings ?? 0} 项</Text>
          </div>
        </Col>
        <Col xs={24} sm={isMobile ? 24 : 8}>
          <div style={{ padding: 12, borderRadius: 8, background: '#f8fafc', textAlign: 'center' }}>
            <ThunderboltOutlined style={{ fontSize: 24, marginBottom: 6, color: '#ea580c' }} />
            <Text strong style={{ display: 'block', fontSize: 13 }}>合并风险</Text>
            <Text style={{ fontSize: 12 }}>{riskLabel[data.merge_risk_level || ''] || data.merge_risk_level || '-'}</Text>
          </div>
        </Col>
      </Row>
      <Descriptions size="small" column={isMobile ? 1 : 2} style={{ marginTop: 16 }} bordered>
        <Descriptions.Item label="复核状态">{statusLabel[data.merge_review_status || ''] || data.merge_review_status || '-'}</Descriptions.Item>
        <Descriptions.Item label="需人工复核">{data.merge_requires_human_review ? <Tag color="orange">是</Tag> : <Tag color="green">否</Tag>}</Descriptions.Item>
        <Descriptions.Item label="确定违规">{data.merge_confirmed_count ?? 0} 项</Descriptions.Item>
        <Descriptions.Item label="高风险">{data.merge_high_risk_count ?? 0} 项</Descriptions.Item>
      </Descriptions>
      {data.routing_reasoning && (
        <Alert message="路由推理" description={data.routing_reasoning} type="info" showIcon style={{ marginTop: 12 }} />
      )}
    </Card>
  );
};
