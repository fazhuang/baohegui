/**
 * ReportPage — 合规审查报告详情
 *
 * 编排层：组合 features/report 中的组件。
 * 数据加载、状态管理和页面布局集中在此。
 */

import React, { useEffect, useMemo, useState, useCallback } from 'react';
import {
  Card, Table, Button, Space, Typography, Spin,
  Alert, Row, Col, Empty, Select,
} from 'antd';
import {
  DownloadOutlined, FileExcelOutlined, WarningFilled,
  ExperimentOutlined, DollarOutlined, WarningOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { useParams } from 'react-router-dom';
import { getReport, getReportExcelUrl, getReportPdfUrl } from '../services/api';
import type { ComplianceReport, RuleViolation, LLMViolation } from '../types';
import { getErrorMessage } from '../utils/error';
import {
  getRiskTag, extractSectionName,
  type PipelineSummaryData,
} from '../features/report/utils';
import {
  ScoreRing, ScoreBar, RadarChart,
  RuleDetailRow as RuleDetail, LlmDetailRow as LlmDetail,
  PriorityCard, RiskHeatmap, PipelineSummary,
  MobileRuleCard, MobileLlmCard,
} from '../features/report/components';

const { Title, Text } = Typography;

// ── 移动端检测 ──────────────────────────────────────────────
function useMobile(): boolean {
  const [mobile, setMobile] = useState(window.innerWidth < 768);
  useEffect(() => {
    const onResize = () => setMobile(window.innerWidth < 768);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return mobile;
}

// ═══════════════════════════════════════════════════════════════
// 主页面组件
// ═══════════════════════════════════════════════════════════════

const ReportPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const isMobile = useMobile();
  const [report, setReport] = useState<ComplianceReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sectionFilter, setSectionFilter] = useState<string | null>(null);
  const [riskFilter, setRiskFilter] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      setReport(await getReport(Number(id)));
    } catch (e: unknown) {
      setError(getErrorMessage(e, '报告加载失败'));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // ── 派生数据 ──────────────────────────────────────────────
  const sectionNames = useMemo(() => {
    const names = new Set<string>();
    (report?.rule_violations || []).forEach((v: RuleViolation) => names.add(extractSectionName(v.location || '')));
    return Array.from(names).sort();
  }, [report]);

  const sectionOptions = sectionNames.map(s => ({ value: s, label: s }));
  const riskOptions = [
    { value: 'high', label: '高风险' },
    { value: 'medium', label: '中风险' },
    { value: 'low', label: '低风险' },
  ];
  const sourceOptions = [
    { value: 'rule', label: '规则引擎' },
    { value: 'llm', label: 'AI语义' },
  ];

  // ── 加载态 ────────────────────────────────────────────────
  if (loading) {
    return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" tip="加载报告中..." /></div>;
  }

  // ── 错误态 ────────────────────────────────────────────────
  if (error || !report) {
    return (
      <Alert type="error" message="报告加载失败" description={error || '报告不存在'}
        action={<Button size="small" onClick={load} icon={<ReloadOutlined />}>重试</Button>} />
    );
  }

  const { rule_violations, llm_violations } = report;
  const pipelineData: PipelineSummaryData = {
    traffic_light: (report as any).traffic_light,
    routing_reasoning: (report as any).routing_reasoning,
    parameter_bias_score: (report as any).parameter_bias_score,
    parameter_bias_findings: (report as any).parameter_bias_findings,
    merge_risk_level: (report as any).merge_risk_level,
    merge_review_status: (report as any).merge_review_status,
    merge_requires_human_review: (report as any).merge_requires_human_review,
    merge_confirmed_count: (report as any).merge_confirmed_count,
    merge_high_risk_count: (report as any).merge_high_risk_count,
  };

  const total = rule_violations.length + llm_violations.length;
  const ruleColumns = [
    { title: '规则ID', dataIndex: 'rule_id', key: 'rule_id', width: 120 },
    { title: '风险等级', dataIndex: 'risk_level', key: 'risk_level', width: 90, render: (v: string) => getRiskTag(v) },
    { title: '描述', dataIndex: 'description', key: 'description' },
    { title: '章节', key: 'section', width: 100, render: (_: unknown, r: RuleViolation) => extractSectionName(r.location || '') },
  ];
  const llmColumns = [
    { title: '类型', dataIndex: 'type', key: 'type', width: 100 },
    { title: '风险等级', dataIndex: 'risk_level', key: 'risk_level', width: 90, render: (v: string) => getRiskTag(v) },
    { title: '判断理由', dataIndex: 'reason', key: 'reason' },
    { title: '章节', key: 'section', width: 100, render: (_: unknown, r: LLMViolation) => extractSectionName(r.section || '') },
  ];

  // ── 桌面版 ────────────────────────────────────────────────
  if (!isMobile) {
    return (
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <Title level={4} style={{ margin: 0 }}>{report.file_name}</Title>
          <Space wrap>
            <Button icon={<DownloadOutlined />} onClick={() => { getReportPdfUrl(Number(id)).then(url => window.open(url)); }}>下载PDF</Button>
            <Button icon={<FileExcelOutlined />} onClick={() => { getReportExcelUrl(Number(id)).then(url => window.open(url)); }}>导出Excel</Button>
          </Space>
        </div>

        {/* 评审概览 */}
        <Row gutter={[16, 16]}>
          <Col flex="240px"><ScoreRing score={report.total_score} /></Col>
          <Col flex="auto">
            <Card size="small" style={{ borderRadius: 12 }}>
              <ScoreBar label="章节完整性" value={report.section_score} icon={<ExperimentOutlined />} />
              <ScoreBar label="关键字合规" value={report.keyword_score} icon={<ExperimentOutlined />} />
              <ScoreBar label="禁用词检查" value={report.forbidden_score} icon={<WarningFilled />} />
              <ScoreBar label="语义审查" value={report.semantic_score} icon={<ExperimentOutlined />} />
            </Card>
          </Col>
          <Col flex="240px">
            <RadarChart scores={[
              { label: '章节', value: report.section_score },
              { label: '关键字', value: report.keyword_score },
              { label: '禁用词', value: report.forbidden_score },
              { label: '语义', value: report.semantic_score },
            ]} size={220} />
          </Col>
        </Row>

        {/* LLM 用量 + 去重统计 */}
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col span={12}>
            <Card size="small" title={<Text strong>LLM 模型与消耗</Text>} style={{ borderRadius: 12 }}>
              <Space direction="vertical" size={4}>
                <Space size={24}>
                  <div><Text type="secondary" style={{ fontSize: 12 }}>模型</Text><br /><Text strong>{report.llm_model_used || '—'}</Text></div>
                  <div><Text type="secondary" style={{ fontSize: 12 }}>Token</Text><br /><Text strong>{report.llm_tokens_used || '—'}</Text></div>
                  <div><Text type="secondary" style={{ fontSize: 12 }}>费用</Text><br /><Text strong>¥{Number(report.llm_cost_yuan || 0).toFixed(4)}</Text></div>
                </Space>
                {report.llm_error && <Alert message={report.llm_error} type="warning" showIcon style={{ marginTop: 8 }} />}
              </Space>
            </Card>
          </Col>
          <Col span={12}>
            <Card size="small" title={<Text strong>去重统计</Text>} style={{ borderRadius: 12 }}>
              <Space direction="vertical" size={4}>
                <div><Text type="secondary" style={{ fontSize: 12 }}>跨引擎去重</Text><br /><Text strong>{report.dedup_cross_engine} 条</Text></div>
                <div><Text type="secondary" style={{ fontSize: 12 }}>引擎内去重</Text><br /><Text strong>{report.dedup_intra_engine} 条</Text></div>
              </Space>
            </Card>
          </Col>
        </Row>

        {/* 管线摘要 */}
        <div style={{ marginTop: 16 }}>
          <PipelineSummary data={pipelineData} isMobile={isMobile} />
        </div>

        {/* 优先级 + 热力图 */}
        <PriorityCard violations={rule_violations} llmViolations={llm_violations} />
        <RiskHeatmap violations={rule_violations} llmViolations={llm_violations} />

        {/* 筛选栏 */}
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space wrap>
            <Select placeholder="章节筛选" allowClear style={{ width: 150 }} options={sectionOptions}
              value={sectionFilter} onChange={v => setSectionFilter(v || null)} />
            <Select placeholder="风险等级" allowClear style={{ width: 120 }} options={riskOptions}
              value={riskFilter} onChange={v => setRiskFilter(v || null)} />
            <Select placeholder="来源" allowClear style={{ width: 120 }} options={sourceOptions}
              value={sourceFilter} onChange={v => setSourceFilter(v || null)} />
            <Text type="secondary">共 {total} 项 · 高风险 {report.high_risk_count} · 中风险 {report.medium_risk_count} · 低风险 {report.low_risk_count}</Text>
          </Space>
        </Card>

        {/* 违规表格 */}
        {sourceFilter !== 'llm' && (
          <Card title={<Space><WarningOutlined /><span>规则引擎违规</span></Space>} style={{ borderRadius: 12, marginBottom: 16 }}>
            <Table dataSource={rule_violations} rowKey="rule_id" size="small" pagination={{ pageSize: 10 }}
              columns={ruleColumns} expandable={{ expandedRowRender: (r: RuleViolation) => <RuleDetail record={r} /> }} />
          </Card>
        )}
        {sourceFilter !== 'rule' && (
          <Card title={<Space><DollarOutlined /><span>AI 语义审查</span></Space>} style={{ borderRadius: 12 }}>
            <Table dataSource={llm_violations} rowKey={(_, i) => `llm-${i}`} size="small" pagination={{ pageSize: 10 }}
              columns={llmColumns} expandable={{ expandedRowRender: (r: LLMViolation) => <LlmDetail record={r} /> }} />
          </Card>
        )}
      </div>
    );
  }

  // ── 移动版 ────────────────────────────────────────────────
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Title level={5} style={{ margin: 0 }}>{report.file_name}</Title>
        <Space>
          <Button size="small" icon={<DownloadOutlined />} onClick={() => { getReportPdfUrl(Number(id)).then(url => window.open(url)); }}>PDF</Button>
          <Button size="small" icon={<FileExcelOutlined />} onClick={() => { getReportExcelUrl(Number(id)).then(url => window.open(url)); }}>Excel</Button>
        </Space>
      </div>

      <ScoreRing score={report.total_score} size={100} />

      <Card size="small" style={{ marginTop: 12, borderRadius: 12 }}>
        <ScoreBar label="章节" value={report.section_score} icon={<ExperimentOutlined />} />
        <ScoreBar label="关键字" value={report.keyword_score} icon={<ExperimentOutlined />} />
        <ScoreBar label="禁用词" value={report.forbidden_score} icon={<WarningFilled />} />
        <ScoreBar label="语义" value={report.semantic_score} icon={<ExperimentOutlined />} />
        <div style={{ marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>模型: {report.llm_model_used || '—'} · Token: {report.llm_tokens_used || '—'} · ¥{Number(report.llm_cost_yuan || 0).toFixed(4)}</Text>
        </div>
      </Card>

      <div style={{ marginTop: 12 }}>
        <PipelineSummary data={pipelineData} isMobile={isMobile} />
      </div>

      <Card size="small" title={`规则引擎违规 (${rule_violations.length})`} style={{ borderRadius: 12, marginTop: 12 }}>
        {rule_violations.length === 0 ? <Empty description="无规则违规" /> : rule_violations.map((v, i) => <MobileRuleCard key={i} v={v} />)}
      </Card>

      <Card size="small" title={`AI 语义审查 (${llm_violations.length})`} style={{ borderRadius: 12, marginTop: 12 }}>
        {llm_violations.length === 0 ? <Empty description="无AI检测风险" /> : llm_violations.map((v, i) => <MobileLlmCard key={i} v={v} />)}
      </Card>
    </div>
  );
};

export default ReportPage;
