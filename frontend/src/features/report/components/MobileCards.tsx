/** Report feature — 移动端卡片组件 */

import React from 'react';
import { Card, Space, Typography } from 'antd';
import type { RuleViolation, LLMViolation } from '../../../types';
import { getRiskTag, getRuleTypeTag, getLlmTypeTag, getRiskBorder } from '../utils';
import { QuoteBlock } from './ReportCharts';

const { Text } = Typography;

export const MobileRuleCard: React.FC<{ v: RuleViolation }> = ({ v }) => (
  <Card size="small" style={{ borderRadius: 10, borderLeft: getRiskBorder(v.risk_level), marginBottom: 10 }}>
    <Space direction="vertical" size={6} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        {getRiskTag(v.risk_level)}
        {getRuleTypeTag(v.rule_type)}
      </div>
      {v.description && <Text style={{ fontSize: 13 }}>{v.description}</Text>}
      {v.text && <QuoteBlock text={v.text} />}
      {v.evidence_text && (
        <div>
          <Text type="secondary" style={{ fontSize: 11 }}>违规证据：</Text>
          <QuoteBlock text={v.evidence_text} />
        </div>
      )}
      <Text type="secondary" style={{ fontSize: 12 }}>{v.suggestion}</Text>
      {v.location && <Text type="secondary" style={{ fontSize: 11 }}>📍 {v.location}</Text>}
    </Space>
  </Card>
);

export const MobileLlmCard: React.FC<{ v: LLMViolation }> = ({ v }) => (
  <Card size="small" style={{ borderRadius: 10, borderLeft: getRiskBorder(v.risk_level), marginBottom: 10 }}>
    <Space direction="vertical" size={6} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        {getRiskTag(v.risk_level)}
        {getLlmTypeTag(v.type)}
      </div>
      {v.reason && <Text style={{ fontSize: 13 }}>{v.reason}</Text>}
      {v.text && <QuoteBlock text={v.text} />}
      <Text type="secondary" style={{ fontSize: 12 }}>{v.suggestion_detail || v.suggestion}</Text>
      {v.section && <Text type="secondary" style={{ fontSize: 11 }}>📍 {v.section}</Text>}
    </Space>
  </Card>
);
