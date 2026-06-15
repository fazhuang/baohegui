/** Upload feature — 步骤定义、管线结果类型、批处理常量 */

import type React from 'react';
import { createElement } from 'react';
import {
  UploadOutlined, FileSearchOutlined, ThunderboltOutlined,
  SafetyOutlined, FlagOutlined, ExperimentOutlined, MergeCellsOutlined,
} from '@ant-design/icons';

// ═══════════════════════════════════════════════════════════════
// 步骤体系
// ═══════════════════════════════════════════════════════════════

export type StepName =
  | 'idle' | 'uploading' | 'parsing' | 'routing'
  | 'rule_engine' | 'parameter_bias' | 'llm_analysis' | 'risk_merge'
  | 'done';

export interface StepConfig {
  key: StepName;
  label: string;
  icon: React.ReactNode;
  subtitle: string;
}

const iconUpload = createElement(UploadOutlined);
const iconParse = createElement(FileSearchOutlined);
const iconRoute = createElement(ThunderboltOutlined);
const iconRule = createElement(SafetyOutlined);
const iconBias = createElement(FlagOutlined);
const iconLLM = createElement(ExperimentOutlined);
const iconMerge = createElement(MergeCellsOutlined);

export const STEPS: StepConfig[] = [
  { key: 'uploading', label: '文件上传', icon: iconUpload, subtitle: '上传并存储文件' },
  { key: 'parsing', label: '文档解析', icon: iconParse, subtitle: '章节结构化抽取' },
  { key: 'routing', label: '智能路由', icon: iconRoute, subtitle: '零Token风险分级' },
  { key: 'rule_engine', label: '规则引擎', icon: iconRule, subtitle: '确定性规则检查' },
  { key: 'parameter_bias', label: '参数倾向性', icon: iconBias, subtitle: '9种违规模式检测' },
  { key: 'llm_analysis', label: 'AI语义审查', icon: iconLLM, subtitle: '17维隐含风险分析' },
  { key: 'risk_merge', label: '风险合并', icon: iconMerge, subtitle: '四路结果汇总' },
];

export const STEP_ORDER: StepName[] = [
  'uploading', 'parsing', 'routing', 'rule_engine',
  'parameter_bias', 'llm_analysis', 'risk_merge', 'done',
];

export const stepIndex = (s: StepName) => STEP_ORDER.indexOf(s);

// ═══════════════════════════════════════════════════════════════
// 管线结果
// ═══════════════════════════════════════════════════════════════

export interface PipelineResult {
  traffic_light: string;
  routing_reasoning: string;
  parameter_bias_score: number;
  parameter_bias_findings: number;
  merge_risk_level: string;
  merge_review_status: string;
  merge_requires_human_review: boolean;
  merge_confirmed_count: number;
  merge_high_risk_count: number;
}

// ═══════════════════════════════════════════════════════════════
// 批上传
// ═══════════════════════════════════════════════════════════════

export const MAX_BATCH = 5;

export interface FileItemData {
  id: number;
  file: File;
  status: 'pending' | 'uploading' | 'checking' | 'done' | 'error';
  errorMsg?: string;
  result?: { report_id: number; score: number; pipeline?: PipelineResult };
  dbId?: number;
}
