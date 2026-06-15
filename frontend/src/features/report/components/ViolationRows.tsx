/** Report feature — 违规详情行 (规则引擎 + LLM) */

import React from 'react';
import { Space, Tag, Typography } from 'antd';
import type { RuleViolation, LLMViolation } from '../../../types';
import { getRuleTypeTag, type RuleProvenance } from '../utils';
import { QuoteBlock } from './ReportCharts';

const { Text } = Typography;

/** 规则引擎违规详情的展开行 */
export const RuleDetailRow: React.FC<{ record: RuleViolation; provenance?: RuleProvenance }> = ({ record, provenance }) => (
  <div style={{ padding: '12px 24px' }}>
    {provenance && (
      <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <Text type="secondary" style={{ fontSize: 11 }}>溯源：</Text>
        {provenance.source_file && (
          <Tag color="geekblue" style={{ fontSize: 10 }}>
            📄 {provenance.source_file}
            {provenance.source_version && ` v${provenance.source_version}`}
          </Tag>
        )}
        {provenance.source_url ? (
          <a href={provenance.source_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11 }}>查看法规原文 →</a>
        ) : provenance.provenance ? (
          <Text type="secondary" style={{ fontSize: 11, maxWidth: 300 }} ellipsis>{provenance.provenance}</Text>
        ) : null}
        {provenance.last_updated && (
          <Text type="secondary" style={{ fontSize: 10 }}>更新于 {provenance.last_updated}</Text>
        )}
      </div>
    )}
    {record.evidence_text ? (
      <div style={{ marginBottom: 10 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>违规证据（原文高亮）：</Text>
        <QuoteBlock text={record.evidence_text} />
      </div>
    ) : record.text ? (
      <div style={{ marginBottom: 10 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>原文引用：</Text>
        <QuoteBlock text={record.text} />
      </div>
    ) : null}
    {(record.start_offset !== undefined || record.end_offset !== undefined) && (
      <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 6 }}>
        📍 位置: {record.start_offset ?? '开头'} - {record.end_offset ?? '结尾'}
        {record.location && <span> ({record.location})</span>}
      </Text>
    )}
    <Space size={[8, 4]} wrap>
      {getRuleTypeTag(record.rule_type)}
      {record.law_ref && <Tag color="blue">{record.law_ref}</Tag>}
      <Tag>权重 {record.weight}</Tag>
    </Space>
    {record.platform_codes?.length > 0 && (
      <div style={{ marginTop: 6 }}>
        <Text type="secondary" style={{ fontSize: 11 }}>平台规则：</Text>
        {record.platform_codes.map((c, i) => (
          <Tag key={i} style={{ fontSize: 11 }}>{c.platform}({c.code})</Tag>
        ))}
      </div>
    )}
  </div>
);

/** LLM 语义引擎违规详情的展开行 */
export const LlmDetailRow: React.FC<{ record: LLMViolation }> = ({ record }) => (
  <div style={{ padding: '12px 24px' }}>
    {record.text && (
      <div style={{ marginBottom: 10 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>原文引用：</Text>
        <QuoteBlock text={record.text} />
      </div>
    )}
    {record.evidence_text && (
      <div style={{ marginBottom: 10 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>违规证据：</Text>
        <QuoteBlock text={record.evidence_text} />
      </div>
    )}
    <div style={{ marginBottom: 6 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>判断理由：</Text>
      <Text style={{ fontSize: 13 }}>{record.reason}</Text>
    </div>
    {record.legal_basis && (
      <div style={{ marginBottom: 6 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>法律依据：</Text>
        <Text style={{ fontSize: 13 }}>{record.legal_basis}</Text>
      </div>
    )}
    <Space size={[8, 4]} wrap>
      {record.law_ref && <Tag color="blue">{record.law_ref}</Tag>}
      <Text type="secondary" style={{ fontSize: 12 }}>建议：{record.suggestion_detail || record.suggestion}</Text>
    </Space>
  </div>
);
