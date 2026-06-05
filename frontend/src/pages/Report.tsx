import React, { useEffect, useMemo, useState } from 'react'
import {
  Card, Descriptions, Table, Tag, Button, Space, Typography, Spin,
  Alert, Progress, Tooltip, Row, Col, Empty, Select,
} from 'antd'
import {
  DownloadOutlined, WarningFilled, InfoCircleFilled,
  CheckCircleFilled, ExperimentOutlined, DollarOutlined,
  ThunderboltOutlined, MergeCellsOutlined,
  SafetyCertificateOutlined, FileSearchOutlined,
  FlagOutlined, HeatMapOutlined, BranchesOutlined,
  AimOutlined, FileTextOutlined,
} from '@ant-design/icons'
import { useParams } from 'react-router-dom'
import { getReport, getReportPdfUrl } from '../services/api'
import type { ComplianceReport, RuleViolation, LLMViolation } from '../types'

const { Title, Text } = Typography

// ── 移动端检测 ──────────────────────────────────────────────
function useMobile(): boolean {
  const [mobile, setMobile] = useState(window.innerWidth < 768)
  useEffect(() => {
    const onResize = () => setMobile(window.innerWidth < 768)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return mobile
}

// ═══════════════════════════════════════════════════════════════
// 工具函数
// ═══════════════════════════════════════════════════════════════

const getScoreColor = (score: number) => {
  if (score >= 85) return 'var(--color-success)'
  if (score >= 60) return 'var(--color-warning)'
  return 'var(--color-error)'
}

const getRiskColor = (level: string) => {
  const map: Record<string, string> = {
    high: 'var(--color-error)', medium: 'var(--color-warning)', low: 'var(--color-success)',
  }
  return map[level] || 'var(--color-text-secondary)'
}

const getRiskBorder = (level: string) => `3px solid ${getRiskColor(level)}`

const getRiskTag = (level: string) => {
  const map: Record<string, { color: string; label: string }> = {
    high: { color: 'red', label: '高风险' },
    medium: { color: 'gold', label: '中风险' },
    low: { color: 'green', label: '低风险' },
  }
  const { color, label } = map[level] || { color: 'default', label: level }
  return <Tag color={color}>{label}</Tag>
}

const getRuleTypeTag = (type: string) => {
  const map: Record<string, string> = {
    chapter_required: '章节缺失',
    keyword_required: '关键字缺',
    forbidden: '禁用词',
  }
  return <Tag>{map[type] || type}</Tag>
}

const getLlmTypeTag = (type: string) => {
  const map: Record<string, { color: string; label: string }> = {
    exclusivity: { color: 'red', label: '排他性' },
    bias: { color: 'orange', label: '倾向性' },
    hidden_barrier: { color: 'purple', label: '隐性壁垒' },
    ambiguity: { color: 'blue', label: '条款含糊' },
    high_risk: { color: 'volcano', label: '质疑风险' },
  }
  const { color, label } = map[type] || { color: 'default', label: type }
  return <Tag color={color}>{label}</Tag>
}

const getViolationIcon = (level: string) => {
  if (level === 'high') return <WarningFilled style={{ color: 'var(--color-error)', fontSize: 16 }} />
  if (level === 'medium') return <InfoCircleFilled style={{ color: 'var(--color-warning)', fontSize: 16 }} />
  return <CheckCircleFilled style={{ color: 'var(--color-success)', fontSize: 16 }} />
}

const formatText = (t: string) =>
  t.length > 200 ? t.slice(0, 200) + '…' : t

/**
 * 从违规位置字符串中提取章节名称。
 * 支持格式: "第一章 招标公告 > 2.1 项目概况", "资格要求-3.2", "评审办法"
 */
const extractSectionName = (loc: string): string => {
  if (!loc) return '其他'
  const m = loc.match(/^[第]?[一二三四五六七八九十\d]+[章节篇部]\s*[>＞\-—\s]*(\S+)/)
  if (m) return m[1] || m[0]
  const first = loc.split(/[>＞\-—\n]/)[0].trim()
  return first.length > 20 ? first.slice(0, 20) + '…' : (first || '其他')
}

// ═══════════════════════════════════════════════════════════════
// SVG 雷达图
// ═══════════════════════════════════════════════════════════════

const RadarChart: React.FC<{
  scores: { label: string; value: number }[]
  size?: number
}> = ({ scores, size = 240 }) => {
  const cx = size / 2
  const cy = size / 2
  const r = size * 0.38
  const levels = [25, 50, 75, 100]
  const angles = scores.map((_, i) => (i * 2 * Math.PI) / scores.length - Math.PI / 2)

  const gridPoints = (level: number) =>
    angles.map(a => ({
      x: cx + (r * level) / 100 * Math.cos(a),
      y: cy + (r * level) / 100 * Math.sin(a),
    }))

  const dataPoints = scores.map((s, i) => ({
    x: cx + (r * s.value) / 100 * Math.cos(angles[i]),
    y: cy + (r * s.value) / 100 * Math.sin(angles[i]),
  }))

  const polyStr = dataPoints.map(p => `${p.x},${p.y}`).join(' ')

  return (
    <svg width={size} height={size} style={{ display: 'block', margin: '0 auto' }}>
      {levels.map(lv => {
        const pts = gridPoints(lv)
        return (
          <polygon
            key={lv}
            points={pts.map(p => `${p.x},${p.y}`).join(' ')}
            fill="none"
            stroke="var(--color-border)"
            strokeWidth={1}
            strokeDasharray={lv === 100 ? 'none' : '4,2'}
          />
        )
      })}
      {angles.map((a, i) => (
        <line
          key={i}
          x1={cx} y1={cy}
          x2={cx + r * Math.cos(a)} y2={cy + r * Math.sin(a)}
          stroke="var(--color-border)"
          strokeWidth={1}
        />
      ))}
      <polygon points={polyStr} fill="rgba(37, 99, 235, 0.12)" stroke="var(--color-action)" strokeWidth={2} />
      {dataPoints.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={4} fill="var(--color-action)" stroke="#fff" strokeWidth={2} />
      ))}
      {scores.map((s, i) => {
        const labelR = r * 1.25
        const lx = cx + labelR * Math.cos(angles[i])
        const ly = cy + labelR * Math.sin(angles[i])
        const anchor =
          Math.abs(angles[i]) < 0.1 ? 'middle' :
          angles[i] > 0 && angles[i] < Math.PI ? 'start' : 'end'
        return (
          <g key={i}>
            <text x={lx} y={ly - 8} textAnchor={anchor} fontSize={11} fill="var(--color-text-secondary)">{s.label}</text>
            <text x={lx} y={ly + 8} textAnchor={anchor} fontSize={13} fontWeight="bold" fill={getScoreColor(s.value)}>{s.value}</text>
          </g>
        )
      })}
    </svg>
  )
}

// ═══════════════════════════════════════════════════════════════
// 评分圆环
// ═══════════════════════════════════════════════════════════════

const ScoreRing: React.FC<{ score: number; size?: number }> = ({ score, size = 120 }) => {
  const color = getScoreColor(score)
  const sw = 8
  const radius = (size - sw) / 2
  const circum = 2 * Math.PI * radius
  const offset = circum - (score / 100) * circum
  return (
    <div style={{ position: 'relative', width: size, height: size, margin: '0 auto' }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke="var(--color-border)" strokeWidth={sw} />
        <circle cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke={color} strokeWidth={sw}
          strokeDasharray={circum} strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dashoffset 1s ease-in-out' }} />
      </svg>
      <div style={{
        position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
      }}>
        <Text style={{ fontSize: 28, fontWeight: 'bold', color, lineHeight: 1 }}>{score}</Text>
        <Text style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginTop: 2 }}>合规评分</Text>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 评分条 (compact)
// ═══════════════════════════════════════════════════════════════

const ScoreBar: React.FC<{ label: string; value: number; icon: React.ReactNode }> = ({
  label, value, icon,
}) => (
  <div style={{ marginBottom: 10 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
      <Space size={4}>
        {icon}
        <Text style={{ fontSize: 12 }}>{label}</Text>
      </Space>
      <Text strong style={{ color: getScoreColor(value), fontSize: 13 }}>{value}</Text>
    </div>
    <Progress percent={value} size="small"
      strokeColor={getScoreColor(value)} trailColor="var(--color-bg)" showInfo={false} />
  </div>
)

// ═══════════════════════════════════════════════════════════════
// 展开详情
// ═══════════════════════════════════════════════════════════════

const QuoteBlock: React.FC<{ text: string }> = ({ text }) => (
  <div style={{
    background: 'var(--color-bg)',
    borderLeft: '3px solid var(--color-border)',
    padding: '8px 12px', margin: '6px 0', borderRadius: '0 4px 4px 0',
    fontFamily: 'SF Mono, Monaco, monospace', fontSize: 12, color: 'var(--color-text)',
    whiteSpace: 'pre-wrap', wordBreak: 'break-all',
  }}>
    {formatText(text)}
  </div>
)

const ruleDetailRow = (record: RuleViolation) => (
  <div style={{ padding: '12px 24px' }}>
    {/* 原文引用 — 来自规则引擎的 evidence_text 或 text */}
    {(record as any).evidence_text ? (
      <div style={{ marginBottom: 10 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>违规证据（原文高亮）：</Text>
        <QuoteBlock text={(record as any).evidence_text} />
      </div>
    ) : record.text ? (
      <div style={{ marginBottom: 10 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>原文引用：</Text>
        <QuoteBlock text={record.text} />
      </div>
    ) : null}
    {((record as any).start_offset !== undefined || (record as any).end_offset !== undefined) && (
      <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 6 }}>
        📍 位置: {(record as any).start_offset ?? '开头'} - {(record as any).end_offset ?? '结尾'}
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
)

const llmDetailRow = (record: LLMViolation) => (
  <div style={{ padding: '12px 24px' }}>
    {/* 原文证据 — 高亮引用 */}
    {record.text && (
      <div style={{ marginBottom: 10 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>原文引用：</Text>
        <QuoteBlock text={record.text} />
      </div>
    )}
    {/* M2-1 三段式解释: 证据 → 法律依据 → 整改建议 */}
    {(record as any).evidence_text && (
      <div style={{ marginBottom: 10 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>违规证据：</Text>
        <QuoteBlock text={(record as any).evidence_text} />
      </div>
    )}
    <div style={{ marginBottom: 6 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>判断理由：</Text>
      <Text style={{ fontSize: 13 }}>{record.reason}</Text>
    </div>
    {(record as any).legal_basis && (
      <div style={{ marginBottom: 6 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>法律依据：</Text>
        <Text style={{ fontSize: 13 }}>{(record as any).legal_basis}</Text>
      </div>
    )}
    <Space size={[8, 4]} wrap>
      {record.law_ref && <Tag color="blue">{record.law_ref}</Tag>}
      <Text type="secondary" style={{ fontSize: 12 }}>建议：{(record as any).suggestion_detail || record.suggestion}</Text>
    </Space>
  </div>
)

// ═══════════════════════════════════════════════════════════════
// 整改优先级卡片 — 红色左边条 + 编号
// ═══════════════════════════════════════════════════════════════

const PriorityCard: React.FC<{
  violations: RuleViolation[]
  llmViolations: LLMViolation[]
}> = ({ violations, llmViolations }) => {
  const all = useMemo(() => {
    const rules = violations.map(v => ({
      key: v.rule_id,
      risk: v.risk_level,
      weight: v.weight,
      desc: v.description,
      suggestion: v.suggestion,
      law_ref: v.law_ref,
      source: 'rule' as const,
    }))
    const llms = llmViolations.map((v, i) => ({
      key: `llm-${i}`,
      risk: v.risk_level,
      weight: v.weight,
      desc: v.reason,
      suggestion: v.suggestion,
      law_ref: v.law_ref,
      source: 'llm' as const,
    }))
    const order: Record<string, number> = { high: 0, medium: 1, low: 2 }
    return [...rules, ...llms]
      .sort((a, b) => order[a.risk] - order[b.risk] || b.weight - a.weight)
      .slice(0, 5)
  }, [violations, llmViolations])

  if (all.length === 0) return null

  return (
    <Card
      title={
        <Space>
          <FlagOutlined style={{ color: 'var(--color-error)' }} />
          <span>优先整改建议</span>
          <Tag color="red" style={{ borderRadius: 10 }}>前 {all.length} 项</Tag>
        </Space>
      }
      className="card-accent-red"
      style={{ marginBottom: 20, borderRadius: 12 }}
    >
      {all.map((item, i) => (
        <div
          key={item.key}
          className="priority-card"
          style={{ marginBottom: i < all.length - 1 ? 10 : 0 }}
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
            <span className="priority-number">#{i + 1}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Space size={[4, 4]} wrap style={{ marginBottom: 4 }}>
                {getRiskTag(item.risk)}
                {item.source === 'rule'
                  ? <Tag>规则引擎</Tag>
                  : <Tag color="cyan">AI语义</Tag>}
              </Space>
              <Text strong style={{ fontSize: 14, display: 'block', marginBottom: 4 }}>{item.desc}</Text>
              <Text type="secondary" style={{ fontSize: 13, display: 'block', marginBottom: 4 }}>
                建议措施：{item.suggestion}
              </Text>
              {item.law_ref && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  法规依据：{item.law_ref}
                </Text>
              )}
            </div>
          </div>
        </div>
      ))}
    </Card>
  )
}

// ═══════════════════════════════════════════════════════════════
// 风险热力图 — 章节维度违规分布
// ═══════════════════════════════════════════════════════════════

const RiskHeatmap: React.FC<{
  ruleViolations: RuleViolation[]
  llmViolations: LLMViolation[]
}> = ({ ruleViolations, llmViolations }) => {
  const sectionRisks = useMemo(() => {
    const sectionCounts: Record<string, { high: number; medium: number; low: number; total: number }> = {}

    for (const v of ruleViolations) {
      const loc = v.location || v.description || ''
      const section = extractSectionName(loc)
      if (!sectionCounts[section]) sectionCounts[section] = { high: 0, medium: 0, low: 0, total: 0 }
      const risk = v.risk_level || 'low'
      sectionCounts[section][risk as keyof typeof sectionCounts[string]]++
      sectionCounts[section].total++
    }

    for (const v of llmViolations) {
      const section = v.section || '其他'
      if (!sectionCounts[section]) sectionCounts[section] = { high: 0, medium: 0, low: 0, total: 0 }
      const risk = v.risk_level || 'low'
      sectionCounts[section][risk as keyof typeof sectionCounts[string]]++
      sectionCounts[section].total++
    }

    return Object.entries(sectionCounts)
      .map(([name, counts]) => ({ name, ...counts }))
      .sort((a, b) => b.total - a.total)
  }, [ruleViolations, llmViolations])

  if (sectionRisks.length === 0) return null

  const maxTotal = sectionRisks[0]?.total || 1

  return (
    <Card
      title={
        <Space>
          <HeatMapOutlined style={{ color: 'var(--color-error)' }} />
          <span>风险热力图</span>
          <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
            章节维度违规分布
          </Text>
        </Space>
      }
      size="small"
      style={{ marginBottom: 16, borderRadius: 12 }}
    >
      {sectionRisks.map(s => (
        <div key={s.name} style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <Text strong style={{ fontSize: 13 }}>{s.name}</Text>
            <Space size={4}>
              {s.high > 0 && <Tag color="red" style={{ fontSize: 11, lineHeight: '18px' }}>高 {s.high}</Tag>}
              {s.medium > 0 && <Tag color="gold" style={{ fontSize: 11, lineHeight: '18px' }}>中 {s.medium}</Tag>}
              {s.low > 0 && <Tag color="green" style={{ fontSize: 11, lineHeight: '18px' }}>低 {s.low}</Tag>}
            </Space>
          </div>
          <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', background: '#f0f0f0' }}>
            {s.high > 0 && (
              <div style={{ width: `${(s.high / maxTotal) * 100}%`, background: 'var(--color-error)', transition: 'width 0.4s' }} />
            )}
            {s.medium > 0 && (
              <div style={{ width: `${(s.medium / maxTotal) * 100}%`, background: 'var(--color-warning)', transition: 'width 0.4s' }} />
            )}
            {s.low > 0 && (
              <div style={{ width: `${(s.low / maxTotal) * 100}%`, background: 'var(--color-success)', transition: 'width 0.4s' }} />
            )}
          </div>
          <Text type="secondary" style={{ fontSize: 11, marginTop: 2, display: 'block' }}>
            共 {s.total} 项违规
          </Text>
        </div>
      ))}
    </Card>
  )
}

// ═══════════════════════════════════════════════════════════════
// 五层流水线摘要
// ═══════════════════════════════════════════════════════════════

interface PipelineSummaryData {
  traffic_light?: string
  routing_reasoning?: string
  parameter_bias_score?: number
  parameter_bias_findings?: number
  merge_risk_level?: string
  merge_review_status?: string
  merge_requires_human_review?: boolean
  merge_confirmed_count?: number
  merge_high_risk_count?: number
  parse_quality?: string
  parse_quality_detail?: string
}

const PipelineSummary: React.FC<{ data: PipelineSummaryData }> = ({ data }) => {
  const trafficLightLabel = (light: string) => {
    switch (light) {
      case 'green': return { emoji: '🟢', label: '直接通过', color: 'var(--color-success)' }
      case 'yellow': return { emoji: '🟡', label: '需 LLM 审查', color: 'var(--color-warning)' }
      case 'red': return { emoji: '🔴', label: '高优先级审查', color: 'var(--color-error)' }
      default: return { emoji: '⚪', label: light || '未知', color: 'var(--color-text-secondary)' }
    }
  }

  const mergeRiskLabel = (level?: string) => {
    const map: Record<string, { label: string; color: string }> = {
      'none': { label: '无风险', color: 'green' },
      'low': { label: '低风险', color: 'green' },
      'medium': { label: '中风险', color: 'gold' },
      'high': { label: '高风险', color: 'red' },
      'critical': { label: '严重风险', color: 'volcano' },
    }
    return map[level || ''] || { label: level || '待评估', color: 'default' }
  }

  const reviewStatusLabel = (status?: string) => {
    const map: Record<string, string> = {
      'auto_passed': '自动通过',
      'auto_failed': '自动不通过',
      'needs_review': '待人工复核',
      'reviewed_passed': '复核通过',
      'reviewed_failed': '复核不通过',
    }
    return map[status || ''] || status || '-'
  }

  const parseQualityLabel = (q?: string) => {
    const map: Record<string, { label: string; color: string }> = {
      'ok': { label: '正常', color: 'green' },
      'text_layer': { label: '文本层提取', color: 'green' },
      'ocr': { label: 'OCR 识别', color: 'gold' },
      'partial': { label: '部分解析', color: 'orange' },
      'failed': { label: '解析失败', color: 'red' },
    }
    return map[q || ''] || { label: q || '未知', color: 'default' }
  }

  const tl = trafficLightLabel(data.traffic_light || '')
  const mr = mergeRiskLabel(data.merge_risk_level)
  const pq = parseQualityLabel(data.parse_quality)

  return (
    <Card
      title={
        <Space>
          <BranchesOutlined style={{ color: 'var(--color-action)' }} />
          <span>五层审查流水线摘要</span>
        </Space>
      }
      style={{ marginBottom: 16, borderRadius: 12 }}
    >
      {/* 第一行: 交通灯 + 合并结论 + 解析质量 */}
      <Row gutter={[16, 12]}>
        <Col xs={24} sm={8}>
          <div style={{ background: 'var(--color-bg)', borderRadius: 8, padding: 10 }}>
            <div style={{ fontSize: 18, marginBottom: 4 }}>{tl.emoji} 第0层 路由审查</div>
            <Tag color={tl.color === 'var(--color-success)' ? 'green' : tl.color === 'var(--color-warning)' ? 'gold' : 'red'}>{tl.label}</Tag>
            {data.routing_reasoning && (
              <Text type="secondary" style={{ display: 'block', fontSize: 11, marginTop: 4 }}>
                {data.routing_reasoning}
              </Text>
            )}
          </div>
        </Col>
        <Col xs={24} sm={8}>
          <div style={{ background: 'var(--color-bg)', borderRadius: 8, padding: 10 }}>
            <div style={{ fontSize: 16, marginBottom: 4 }}>
              <MergeCellsOutlined style={{ marginRight: 4 }} />
              汇总层 风险合并
            </div>
            <Space size={4} wrap>
              <Tag color={mr.color}>{mr.label}</Tag>
              {data.merge_review_status && (
                <Tag color="blue">{reviewStatusLabel(data.merge_review_status)}</Tag>
              )}
            </Space>
            <div style={{ marginTop: 4 }}>
              {data.merge_confirmed_count !== undefined && (
                <Tag color="red" style={{ fontSize: 11 }}>确定违规 {data.merge_confirmed_count}</Tag>
              )}
              {data.merge_high_risk_count !== undefined && (
                <Tag color="orange" style={{ fontSize: 11 }}>高风险 {data.merge_high_risk_count}</Tag>
              )}
              {data.merge_requires_human_review && (
                <Tag color="volcano" style={{ fontSize: 11 }}>需人工复核</Tag>
              )}
            </div>
          </div>
        </Col>
        <Col xs={24} sm={8}>
          <div style={{ background: 'var(--color-bg)', borderRadius: 8, padding: 10 }}>
            <div style={{ fontSize: 16, marginBottom: 4 }}>
              <FileTextOutlined style={{ marginRight: 4 }} />
              第4层 解析质量
            </div>
            <Tag color={pq.color}>{pq.label}</Tag>
            {data.parse_quality_detail && (
              <Text type="secondary" style={{ display: 'block', fontSize: 11, marginTop: 4 }}>
                {data.parse_quality_detail}
              </Text>
            )}
          </div>
        </Col>
      </Row>

      {/* 第二行: 参数倾向性 */}
      {(data.parameter_bias_findings !== undefined || data.parameter_bias_score !== undefined) && (
        <Row gutter={[16, 12]} style={{ marginTop: 12 }}>
          <Col span={24}>
            <div style={{ background: '#fff7ed', borderRadius: 8, padding: 10, border: '1px solid #fed7aa' }}>
              <div style={{ fontSize: 16, marginBottom: 4 }}>
                <AimOutlined style={{ marginRight: 4, color: '#ea580c' }} />
                第2层 参数倾向性检测
              </div>
              <Space size={8} wrap>
                {data.parameter_bias_score !== undefined && (
                  <Text strong style={{ color: '#c2410c' }}>
                    风险评分: {data.parameter_bias_score}%
                  </Text>
                )}
                {data.parameter_bias_findings !== undefined && (
                  <Tag color="orange">发现 {data.parameter_bias_findings} 项</Tag>
                )}
              </Space>
            </div>
          </Col>
        </Row>
      )}
    </Card>
  )
}

// ═══════════════════════════════════════════════════════════════
// 移动端违规模板 (保持兼容)
// ═══════════════════════════════════════════════════════════════

const MobileRuleCard: React.FC<{ v: RuleViolation }> = ({ v }) => {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="violation-card" style={{ borderLeft: getRiskBorder(v.risk_level), marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Space size={4} style={{ marginBottom: 4, flexWrap: 'wrap' }}>
            {getRiskTag(v.risk_level)}
            {getRuleTypeTag(v.rule_type)}
          </Space>
          <div style={{ fontWeight: 500, fontSize: 14, marginBottom: 2 }}>{v.description}</div>
          {v.location && <Text type="secondary" style={{ fontSize: 12 }}>{v.location}</Text>}
          <div style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginTop: 4 }}>{v.suggestion}</div>
        </div>
      </div>
      {v.text && (
        <div style={{ marginTop: 6 }}>
          <Button type="link" size="small" onClick={() => setExpanded(!expanded)}
            style={{ padding: 0, fontSize: 12 }}>
            {expanded ? '收起原文' : '查看原文'}
          </Button>
          {expanded && <QuoteBlock text={v.text} />}
          {v.law_ref && <Tag color="blue" style={{ marginTop: 4, fontSize: 11 }}>{v.law_ref}</Tag>}
        </div>
      )}
    </div>
  )
}

const MobileLlmCard: React.FC<{ v: LLMViolation }> = ({ v }) => {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="violation-card" style={{ borderLeft: getRiskBorder(v.risk_level), marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Space size={4} style={{ marginBottom: 4, flexWrap: 'wrap' }}>
            {getRiskTag(v.risk_level)}
            {getLlmTypeTag(v.type)}
            <Tag style={{ fontSize: 11 }}>{v.section}</Tag>
          </Space>
          <div style={{ fontWeight: 500, fontSize: 14, marginBottom: 2 }}>{v.reason}</div>
          <div style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginTop: 4 }}>{v.suggestion}</div>
        </div>
      </div>
      {v.text && (
        <div style={{ marginTop: 6 }}>
          <Button type="link" size="small" onClick={() => setExpanded(!expanded)}
            style={{ padding: 0, fontSize: 12 }}>
            {expanded ? '收起原文' : '查看原文'}
          </Button>
          {expanded && <QuoteBlock text={v.text} />}
          {v.law_ref && <Tag color="blue" style={{ marginTop: 4, fontSize: 11 }}>{v.law_ref}</Tag>}
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 主组件
// ═══════════════════════════════════════════════════════════════

const ReportPage: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const isMobile = useMobile()
  const [report, setReport] = useState<ComplianceReport | null>(null)
  const [loading, setLoading] = useState(true)

  // ── 全局筛选 ──────────────────────────────────────────
  const [globalRisk, setGlobalRisk] = useState<string | null>(null)
  const [globalEngine, setGlobalEngine] = useState<string | null>(null)
  const [globalSection, setGlobalSection] = useState<string | null>(null)

  const riskOptions = [
    { value: 'high', label: '高风险' },
    { value: 'medium', label: '中风险' },
    { value: 'low', label: '低风险' },
  ]

  const engineOptions = [
    { value: 'rule', label: '规则引擎' },
    { value: 'llm', label: 'AI 语义' },
  ]

  useEffect(() => {
    document.title = '合规审查报告 - 包合规'
    if (id) {
      getReport(Number(id))
        .then(setReport)
        .catch(console.error)
        .finally(() => setLoading(false))
    }
  }, [id])

  // 全局筛选
  const filteredRules = useMemo(() => {
    if (!report) return []
    let list = report.rule_violations
    if (globalEngine && globalEngine !== 'rule') return []
    if (globalRisk) list = list.filter(v => v.risk_level === globalRisk)
    if (globalSection) list = list.filter(v => v.location === globalSection)
    return list
  }, [report, globalRisk, globalEngine, globalSection])

  const filteredLlms = useMemo(() => {
    if (!report) return []
    let list = report.llm_violations
    if (globalEngine && globalEngine !== 'llm') return []
    if (globalRisk) list = list.filter(v => v.risk_level === globalRisk)
    if (globalSection) list = list.filter(v => v.section === globalSection)
    return list
  }, [report, globalRisk, globalEngine, globalSection])

  // 章节选项（从数据中提取）
  const sectionOptions = useMemo(() => {
    if (!report) return []
    const sections = new Set<string>()
    report.rule_violations.forEach(v => { if (v.location) sections.add(v.location) })
    report.llm_violations.forEach(v => { if (v.section) sections.add(v.section) })
    return Array.from(sections).map(s => ({ value: s, label: s }))
  }, [report])

  // ── 从 report_data 提取五层流水线数据 ──────────────────
  const pipelineData = useMemo<PipelineSummaryData>(() => {
    if (!report?.report_data) return {}
    try {
      const data = JSON.parse(report.report_data)
      return {
        traffic_light: data.traffic_light,
        routing_reasoning: data.routing_reasoning,
        parameter_bias_score: data.parameter_bias_score,
        parameter_bias_findings: data.parameter_bias_findings,
        merge_risk_level: data.merge_risk_level || data.merge_result?.risk_level,
        merge_review_status: data.merge_review_status || data.merge_result?.review_status,
        merge_requires_human_review: data.merge_requires_human_review ?? data.merge_result?.requires_human_review,
        merge_confirmed_count: data.merge_confirmed_count ?? data.merge_result?.confirmed_count,
        merge_high_risk_count: data.merge_high_risk_count ?? data.merge_result?.high_risk_count,
        parse_quality: data.parse_quality,
        parse_quality_detail: data.parse_quality_detail,
      }
    } catch { return {} }
  }, [report])

  // ── Loading ──────────────────────────────────────────
  if (loading) {
    return (
      <div className="state-container">
        <Spin size="large" />
        <div style={{ marginTop: 16 }}>
          <Text type="secondary">加载报告中...</Text>
        </div>
      </div>
    )
  }

  if (!report) {
    return <Alert message="未找到报告" type="error" showIcon style={{ marginTop: 24 }} />
  }

  const hasViolations = report.total_violations > 0

  const radarScores = [
    { label: '章节完整性', value: report.section_score },
    { label: '关键字合规', value: report.keyword_score },
    { label: '禁用词检查', value: report.forbidden_score },
    { label: 'AI语义分析', value: report.semantic_score },
  ]

  // 表格列定义
  const ruleColumns = [
    {
      title: '', key: 'icon', width: 36,
      render: (_: any, r: RuleViolation) => getViolationIcon(r.risk_level),
    },
    { title: '违规描述', dataIndex: 'description', key: 'description' },
    {
      title: '风险', dataIndex: 'risk_level', key: 'risk_level', width: 90,
      render: (v: string) => getRiskTag(v),
    },
    {
      title: '类型', dataIndex: 'rule_type', key: 'rule_type', width: 90,
      render: (v: string) => getRuleTypeTag(v),
    },
    {
      title: '位置', dataIndex: 'location', key: 'location', width: 160,
      render: (v: string) => v ? <Text code style={{ fontSize: 12 }}>{v}</Text> : '-',
    },
    {
      title: '整改建议', dataIndex: 'suggestion', key: 'suggestion',
      render: (v: string) => <Text style={{ fontSize: 13 }}>{v}</Text>,
    },
  ]

  const llmColumns = [
    {
      title: '', key: 'icon', width: 36,
      render: (_: any, r: LLMViolation) => getViolationIcon(r.risk_level),
    },
    {
      title: '类型', dataIndex: 'type', key: 'type', width: 100,
      render: (v: string) => getLlmTypeTag(v),
    },
    { title: '章节', dataIndex: 'section', key: 'section', width: 120 },
    {
      title: '风险', dataIndex: 'risk_level', key: 'risk_level', width: 90,
      render: (v: string) => getRiskTag(v),
    },
    {
      title: '判断理由', dataIndex: 'reason', key: 'reason',
      render: (v: string) => <Text style={{ fontSize: 13 }}>{v}</Text>,
    },
  ]

  const rowStyle = (risk: string) => ({
    borderLeft: getRiskBorder(risk),
    borderRadius: 4,
    marginBottom: 2,
  })

  const renderRuleTable = (mobile: boolean) => {
    if (mobile) return <div>{filteredRules.map(v => <MobileRuleCard key={v.rule_id} v={v} />)}</div>
    return (
      <Table dataSource={filteredRules} columns={ruleColumns}
        rowKey="rule_id"
        pagination={filteredRules.length > 20 ? { pageSize: 20 } : false}
        size="small"
        onRow={(rec) => ({ style: rowStyle(rec.risk_level) })}
        expandable={{
          expandedRowRender: ruleDetailRow,
          rowExpandable: (r) => !!(r.text || r.law_ref),
        }}
      />
    )
  }

  const renderLLMTable = (mobile: boolean) => {
    if (mobile) return <div>{filteredLlms.map((v, i) => <MobileLlmCard key={`llm-${i}`} v={v} />)}</div>
    return (
      <Table dataSource={filteredLlms} columns={llmColumns}
        rowKey={(_, i) => "llm-" + i}
        pagination={filteredLlms.length > 20 ? { pageSize: 20 } : false}
        size="small"
        onRow={(rec) => ({ style: rowStyle(rec.risk_level) })}
        expandable={{
          expandedRowRender: llmDetailRow,
          rowExpandable: (r) => !!(r.text || r.law_ref || r.reason),
        }}
      />
    )
  }

  // 平台拦截数据
  const platformHits: Record<string, { codes: Set<string>; violations: RuleViolation[]; highCount: number }> = {}
  report.rule_violations.forEach(v => {
    (v.platform_codes || []).forEach(pc => {
      const key = pc.platform || '未知平台'
      if (!platformHits[key]) {
        platformHits[key] = { codes: new Set(), violations: [], highCount: 0 }
      }
      platformHits[key].codes.add(pc.code || '')
      platformHits[key].violations.push(v)
      if (v.risk_level === 'high') platformHits[key].highCount++
    })
  })
  report.llm_violations.filter(v => v.risk_level === 'high').forEach((_lv) => {
    const matchedPlatforms = Object.keys(platformHits)
    matchedPlatforms.forEach(p => {
      platformHits[p].highCount++
    })
  })
  const platforms = Object.entries(platformHits)

  return (
    <div>
      {/* ═══════ 报告头部 ═══════ */}
      <Title level={3} style={{ fontSize: 20, fontWeight: 600, marginBottom: 4 }}>
        合规审查报告
      </Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 20 }}>
        {report.file_name} &middot; {report.check_time}
      </Text>

      {/* ═══════ 五层流水线摘要 ═══════ */}
      {pipelineData.traffic_light && <PipelineSummary data={pipelineData} />}

      {/* ═══════ 报告摘要横向条 ═══════ */}
      <div className="report-summary-strip" style={{ marginBottom: 20 }}>
        {/* 评分环 */}
        <div style={{ flexShrink: 0 }}>
          <ScoreRing score={report.total_score} size={100} />
        </div>

        {/* 分隔 */}
        <div style={{ width: 1, height: 80, background: 'var(--color-border)', flexShrink: 0 }} />

        {/* 四维评分条 */}
        <div style={{ flex: 1, minWidth: 180, padding: '0 8px' }}>
          <ScoreBar label="章节完整性" value={report.section_score}
            icon={<FileSearchOutlined style={{ color: 'var(--color-action)' }} />} />
          <ScoreBar label="关键字合规" value={report.keyword_score}
            icon={<SafetyCertificateOutlined style={{ color: '#7c3aed' }} />} />
          <ScoreBar label="禁用词检查" value={report.forbidden_score}
            icon={<WarningFilled style={{ color: '#ea580c' }} />} />
          <ScoreBar label="AI 语义分析" value={report.semantic_score}
            icon={<ExperimentOutlined style={{ color: '#0891b2' }} />} />
        </div>

        {/* 分隔 */}
        <div style={{ width: 1, height: 80, background: 'var(--color-border)', flexShrink: 0 }} />

        {/* 风险统计 */}
        <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <Tag icon={<WarningFilled />} color="red"
            style={{ padding: '2px 12px', borderRadius: 20, fontSize: 13 }}>
            高风险 {report.high_risk_count}
          </Tag>
          <Tag icon={<InfoCircleFilled />} color="gold"
            style={{ padding: '2px 12px', borderRadius: 20, fontSize: 13 }}>
            中风险 {report.medium_risk_count}
          </Tag>
          <Tag icon={<CheckCircleFilled />} color="green"
            style={{ padding: '2px 12px', borderRadius: 20, fontSize: 13 }}>
            低风险 {report.low_risk_count}
          </Tag>
          <Tag style={{ padding: '2px 12px', borderRadius: 20, fontSize: 13 }}>
            共 {report.total_violations} 项
          </Tag>
        </div>

        {/* 雷达图（桌面端） */}
        <div className="hide-mobile" style={{ flexShrink: 0 }}>
          <RadarChart scores={radarScores} size={140} />
        </div>
      </div>

      {/* ═══════ 全局筛选栏 ═══════ */}
      {hasViolations && (
        <div className="filter-bar" style={{ marginBottom: 20 }}>
          <span className="filter-bar-label">筛选：</span>
          <Select
            allowClear
            placeholder="风险等级"
            options={riskOptions}
            style={{ minWidth: 120 }}
            size="small"
            value={globalRisk}
            onChange={(v) => setGlobalRisk(v || null)}
          />
          <Select
            allowClear
            placeholder="检测引擎"
            options={engineOptions}
            style={{ minWidth: 120 }}
            size="small"
            value={globalEngine}
            onChange={(v) => setGlobalEngine(v || null)}
          />
          {sectionOptions.length > 0 && (
            <Select
              allowClear
              placeholder="章节"
              options={sectionOptions}
              style={{ minWidth: 140 }}
              size="small"
              value={globalSection}
              onChange={(v) => setGlobalSection(v || null)}
            />
          )}
        </div>
      )}

      {/* ═══════ 空状态 ═══════ */}
      {!hasViolations && (
        <Card style={{ marginBottom: 20, borderRadius: 12 }}>
          <Empty
            image={<CheckCircleFilled style={{ fontSize: 64, color: 'var(--color-success)' }} />}
            description={
              <div>
                <Title level={4} style={{ color: 'var(--color-success)', margin: 0 }}>未发现合规问题</Title>
                <Text type="secondary">该招标文件内容完整，未触发合规告警</Text>
              </div>
            }
          />
        </Card>
      )}

      {/* ═══════ 优先整改建议 ═══════ */}
      {hasViolations && (
        <PriorityCard
          violations={report.rule_violations}
          llmViolations={report.llm_violations}
        />
      )}

      {/* ═══════ 风险热力图 ═══════ */}
      {hasViolations && (
        <RiskHeatmap
          ruleViolations={report.rule_violations}
          llmViolations={report.llm_violations}
        />
      )}

      {/* ═══════ 平台拦截预测（独立高亮区域）═══════ */}
      {platforms.length > 0 && (
        <Card
          title={
            <Space>
              <SafetyCertificateOutlined style={{ color: 'var(--color-error)' }} />
              <span>平台拦截预测</span>
              <Tag color="red" style={{ borderRadius: 10 }}>
                {platforms.length} 个平台可能拦截
              </Tag>
            </Space>
          }
          className="card-accent-red"
          style={{ marginBottom: 20, borderRadius: 12 }}
        >
          {platforms.map(([platform, info]) => {
            const interceptRate = Math.min(100, Math.round(info.violations.length * 15 + info.highCount * 20))
            return (
              <Card
                key={platform}
                size="small"
                style={{ marginBottom: 12, borderRadius: 8, borderLeft: '3px solid var(--color-error)' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
                  <Space>
                    <Text strong style={{ fontSize: 15 }}>{platform}</Text>
                    <Tag color="red">拦截概率 ~{interceptRate}%</Tag>
                  </Space>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    命中 {info.codes.size} 条规则，{info.violations.length} 项违规 ({info.highCount} 项高危)
                  </Text>
                </div>
                <div style={{ marginBottom: 6 }}>
                  <Text type="secondary" style={{ fontSize: 11 }}>相关平台规则代码：</Text>
                  {Array.from(info.codes).slice(0, 10).map(code => (
                    <Tag key={code} style={{ fontSize: 11, marginBottom: 4 }} color="volcano">{code}</Tag>
                  ))}
                  {info.codes.size > 10 && (
                    <Tag style={{ fontSize: 11 }}>+{info.codes.size - 10} 条</Tag>
                  )}
                </div>
                {info.violations.filter(v => v.risk_level === 'high').slice(0, 3).map(v => (
                  <div key={v.rule_id} style={{ fontSize: 12, color: 'var(--color-error)', marginBottom: 2 }}>
                    {v.description}
                    {v.suggestion && <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>&rarr; {v.suggestion}</Text>}
                  </div>
                ))}
                {info.violations.filter(v => v.risk_level === 'high').length > 3 && (
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    ...及其他 {info.violations.filter(v => v.risk_level === 'high').length - 3} 项高危违规
                  </Text>
                )}
              </Card>
            )
          })}
          <Alert
            message="以上预测基于当前公共资源交易平台的公开审查规则，实际拦截结果可能因平台规则更新而有所差异"
            type="warning"
            showIcon={false}
            style={{ background: '#fff7ed', border: '1px solid #fed7aa', fontSize: 11, padding: '6px 10px', borderRadius: 6 }}
          />
        </Card>
      )}

      {/* ═══════ 规则引擎违规（橙色色条）═══════ */}
      {report.rule_violations.length > 0 && (
        <Card
          title={
            <div className="table-accent-header">
              <div className="table-accent-dot" style={{ backgroundColor: 'var(--color-warning)' }} />
              <span>规则引擎检测</span>
              <Tag style={{ borderRadius: 10 }}>{filteredRules.length}/{report.rule_violations.length}</Tag>
            </div>
          }
          style={{ marginBottom: 20, borderRadius: 12 }}
        >
          {renderRuleTable(isMobile)}
        </Card>
      )}

      {/* ═══════ AI 语义分析（青色色条）═══════ */}
      {report.llm_violations.length > 0 && (
        <Card
          title={
            <div className="table-accent-header">
              <div className="table-accent-dot" style={{ backgroundColor: '#0891b2' }} />
              <span>AI 语义分析</span>
              <Tag style={{ borderRadius: 10 }}>{filteredLlms.length}/{report.llm_violations.length}</Tag>
            </div>
          }
          style={{ marginBottom: 20, borderRadius: 12 }}
        >
          {renderLLMTable(isMobile)}
        </Card>
      )}

      {/* ═══════ LLM 错误 ═══════ */}
      {report.llm_error && (
        <Alert message="AI 语义分析提示" description={report.llm_error}
          type="warning" showIcon style={{ marginBottom: 20, borderRadius: 8 }} />
      )}

      {/* ═══════ 审核信息 ═══════ */}
      <Card
        title={
          <Space>
            <ThunderboltOutlined style={{ color: 'var(--color-text-secondary)' }} />
            <span>审核信息</span>
          </Space>
        }
        style={{ marginBottom: 20, borderRadius: 12 }}
        size="small"
      >
        <Row gutter={[16, 12]}>
          <Col xs={24} sm={12}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="AI 模型">{report.llm_model_used || '-'}</Descriptions.Item>
              <Descriptions.Item label="Token 消耗">{report.llm_tokens_used?.toLocaleString() || 0}</Descriptions.Item>
              {report.llm_cost_yuan > 0 && (
                <Descriptions.Item label={<><DollarOutlined /> 预估费用</>}>
                  ¥{report.llm_cost_yuan.toFixed(4)}
                </Descriptions.Item>
              )}
            </Descriptions>
          </Col>
          <Col xs={24} sm={12}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="规则引擎规则数">{report.rule_count} 条</Descriptions.Item>
              <Descriptions.Item label={<><MergeCellsOutlined /> 跨引擎去重</>}>
                {report.dedup_cross_engine > 0
                  ? <Text style={{ color: 'var(--color-success)' }}>合并 {report.dedup_cross_engine} 项</Text>
                  : '无重复'}
              </Descriptions.Item>
            </Descriptions>
          </Col>
        </Row>
      </Card>

      {/* ═══════ 下载 PDF — sticky 桌面 / 浮动 移动 ═══════ */}
      <div className={isMobile ? 'fab-pdf-mobile' : 'hide-mobile'} style={{
        textAlign: 'center',
        marginBottom: 40,
      }}>
        <Tooltip title="下载 PDF 格式的合规审查报告">
          <Button type="primary" icon={<DownloadOutlined />} size="large"
            href={getReportPdfUrl(Number(id))} target="_blank"
            style={{ borderRadius: 8, paddingLeft: 32, paddingRight: 32 }}>
            下载 PDF 报告
          </Button>
        </Tooltip>
      </div>

      {/* 移动端浮动下载按钮 */}
      {isMobile && (
        <div className="fab-pdf-mobile" style={{
          position: 'fixed',
          bottom: 72,
          right: 16,
          zIndex: 98,
        }}>
          <Button
            type="primary"
            shape="circle"
            size="large"
            icon={<DownloadOutlined style={{ fontSize: 20 }} />}
            href={getReportPdfUrl(Number(id))}
            target="_blank"
            style={{
              width: 52,
              height: 52,
              boxShadow: '0 4px 16px rgba(30,64,175,0.3)',
            }}
          />
        </div>
      )}
    </div>
  )
}

export default ReportPage
