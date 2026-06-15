/** Report feature — 工具函数与类型 */

import { Tag } from 'antd';
import {
  WarningFilled, InfoCircleFilled, CheckCircleFilled,
} from '@ant-design/icons';

// ═══════════════════════════════════════════════════════════════
// 评分 / 颜色工具
// ═══════════════════════════════════════════════════════════════

const CSS_VAR_ERROR = 'var(--color-error)';
const CSS_VAR_SUCCESS = 'var(--color-success)';
const CSS_VAR_WARNING = 'var(--color-warning)';
const CSS_VAR_TEXT_SEC = 'var(--color-text-secondary)';

export const getScoreColor = (score: number) => {
  if (score >= 85) return CSS_VAR_SUCCESS;
  if (score >= 60) return CSS_VAR_WARNING;
  return CSS_VAR_ERROR;
};

export const getRiskColor = (level: string) => {
  const map: Record<string, string> = {
    high: CSS_VAR_ERROR, medium: CSS_VAR_WARNING, low: CSS_VAR_SUCCESS,
  };
  return map[level] || CSS_VAR_TEXT_SEC;
};

export const getRiskBorder = (level: string) => `3px solid ${getRiskColor(level)}`;

export const getRiskTag = (level: string) => {
  const map: Record<string, { color: string; label: string }> = {
    high: { color: 'red', label: '高风险' },
    medium: { color: 'gold', label: '中风险' },
    low: { color: 'green', label: '低风险' },
  };
  const { color, label } = map[level] || { color: 'default', label: level };
  return <Tag color={color}>{label}</Tag>;
};

export const getRuleTypeTag = (type: string) => {
  const map: Record<string, string> = {
    chapter_required: '章节缺失',
    keyword_required: '关键字缺',
    forbidden: '禁用词',
  };
  return <Tag>{map[type] || type}</Tag>;
};

export const getLlmTypeTag = (type: string) => {
  const map: Record<string, { color: string; label: string }> = {
    exclusivity: { color: 'red', label: '排他性' },
    bias: { color: 'orange', label: '倾向性' },
    hidden_barrier: { color: 'purple', label: '隐性壁垒' },
    ambiguity: { color: 'blue', label: '条款含糊' },
    high_risk: { color: 'volcano', label: '质疑风险' },
  };
  const { color, label } = map[type] || { color: 'default', label: type };
  return <Tag color={color}>{label}</Tag>;
};

export const getViolationIcon = (level: string) => {
  if (level === 'high') return <WarningFilled style={{ color: CSS_VAR_ERROR, fontSize: 16 }} />;
  if (level === 'medium') return <InfoCircleFilled style={{ color: CSS_VAR_WARNING, fontSize: 16 }} />;
  return <CheckCircleFilled style={{ color: CSS_VAR_SUCCESS, fontSize: 16 }} />;
};

export const formatText = (t: string) =>
  t.length > 200 ? t.slice(0, 200) + '…' : t;

export const extractSectionName = (loc: string): string => {
  if (!loc) return '其他';
  const m = loc.match(/^[第]?[一二三四五六七八九十\d]+[章节篇部]\s*[>＞\-—\s]*(\S+)/);
  if (m) return m[1] || m[0];
  const first = loc.split(/[>＞\-—\n]/)[0].trim();
  return first.length > 20 ? first.slice(0, 20) + '…' : (first || '其他');
};

/** 规则溯源元数据 */
export interface RuleProvenance {
  source_file: string;
  source_version: string;
  source_url?: string;
  provenance: string;
  last_updated?: string;
}

/** 管线摘要数据类型 */
export interface PipelineSummaryData {
  traffic_light?: string;
  routing_reasoning?: string;
  parameter_bias_score?: number;
  parameter_bias_findings?: number;
  merge_risk_level?: string;
  merge_review_status?: string;
  merge_requires_human_review?: boolean;
  merge_confirmed_count?: number;
  merge_high_risk_count?: number;
}
