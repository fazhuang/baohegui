import React, { useEffect, useState, useCallback } from 'react'
import {
  Card, Table, Tag, Typography, Spin, Empty, Row, Col, Statistic, message,
} from 'antd'
import {
  SafetyOutlined, TagsOutlined, WarningOutlined,
  ThunderboltOutlined, ReloadOutlined,
} from '@ant-design/icons'
import {
  fetchRulesStats, fetchEffectiveness,
  type RulesStats, type RuleStat,
} from '../../services/rules-admin-api'

const { Title, Text } = Typography

// ── Colour helpers ───────────────────────────────────────────

const RISK_COLORS: Record<string, string> = {
  high: '#dc2626',
  medium: '#eab308',
  low: '#16a34a',
}

const TYPE_COLORS: Record<string, string> = {
  required: '#2563eb',
  forbidden: '#dc2626',
  keyword: '#7c3aed',
  pattern_required: '#0891b2',
  numeric_range: '#ea580c',
  date_interval: '#ca8a04',
  conditional: '#16a34a',
  semantic_required: '#9333ea',
}

function typeLabel(t: string): string {
  const map: Record<string, string> = {
    required: '必填项',
    pattern_required: '模式匹配',
    forbidden: '禁用词',
    keyword: '关键字',
    numeric_range: '数值范围',
    date_interval: '日期区间',
    conditional: '条件触发',
    semantic_required: '语义必填',
    forbidden_pattern: '禁用模式',
  }
  return map[t] || t
}

function categoryLabel(c: string): string {
  const map: Record<string, string> = {
    base: '基础规则',
    platform: '平台规则',
    industry: '行业规则',
    custom: '自定义',
    draft: '草稿',
    qualification: '资格条件',
    evaluation: '评标标准',
    commercial: '商务条款',
    procedural: '程序合规',
    legal_conflict: '法规冲突',
  }
  return map[c] || c
}

// ── Stat card ────────────────────────────────────────────────

interface StatCardProps {
  title: string
  value: number | string
  icon: React.ReactNode
  loading: boolean
}

const StatCard: React.FC<StatCardProps> = ({ title, value, icon, loading }) => (
  <Card style={{ borderRadius: 10, height: '100%' }}>
    {loading ? (
      <Spin size="small" />
    ) : (
      <Row align="middle" gutter={12}>
        <Col>
          <div
            style={{
              width: 46,
              height: 46,
              borderRadius: 10,
              background: 'var(--color-brand-light, #eff6ff)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--color-action, #2563eb)',
              fontSize: 20,
            }}
          >
            {icon}
          </div>
        </Col>
        <Col flex={1}>
          <Statistic title={title} value={value} />
        </Col>
      </Row>
    )}
  </Card>
)

// ── Breakdown tags ───────────────────────────────────────────

const BreakdownTags: React.FC<{
  data: Record<string, number>
  colorMap?: Record<string, string>
  labelFn?: (k: string) => string
}> = ({ data, colorMap, labelFn }) => {
  const entries = Object.entries(data)
  if (entries.length === 0) return <Text type="secondary">暂无数据</Text>

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {entries.map(([key, count]) => (
        <Tag
          key={key}
          color={colorMap?.[key]}
          style={{ fontSize: 12, margin: 0 }}
        >
          {labelFn ? labelFn(key) : key}: {count}
        </Tag>
      ))}
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────

const RulesDashboard: React.FC = () => {
  const [stats, setStats] = useState<RulesStats | null>(null)
  const [effectiveness, setEffectiveness] = useState<RuleStat[]>([])
  const [totalReports, setTotalReports] = useState(0)
  const [statsLoading, setStatsLoading] = useState(true)
  const [effLoading, setEffLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    setError(null)
    try {
      const data = await fetchRulesStats()
      setStats(data)
    } catch (e: any) {
      message.error('加载统计数据失败')
      setError(e.message)
    } finally {
      setStatsLoading(false)
    }
  }, [])

  const loadEffectiveness = useCallback(async () => {
    setEffLoading(true)
    try {
      const data = await fetchEffectiveness()
      setEffectiveness(data.rules)
      setTotalReports(data.total_reports)
    } catch (e: any) {
      message.error('加载效力数据失败')
    } finally {
      setEffLoading(false)
    }
  }, [])

  useEffect(() => {
    loadStats()
    loadEffectiveness()
  }, [loadStats, loadEffectiveness])

  // ── Loading state ──────────────────────────────────────
  if (statsLoading && effLoading && !stats && effectiveness.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" tip="加载规则统计数据..." />
      </div>
    )
  }

  // ── Error state ────────────────────────────────────────
  if (error && !stats) {
    return (
      <div style={{ padding: 24 }}>
        <Title level={3}>规则看板</Title>
        <Card>
          <Empty
            description={`加载失败: ${error}`}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            <a onClick={loadStats} style={{ cursor: 'pointer' }}>
              <ReloadOutlined /> 重试
            </a>
          </Empty>
        </Card>
      </div>
    )
  }

  return (
    <div>
      {/* ── Header ── */}
      <div style={{ marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>规则看板</Title>
          <Text type="secondary">
            规则统计与效力分析
            {stats?.last_reload && ` · 上次加载: ${new Date(stats.last_reload).toLocaleString('zh-CN')}`}
          </Text>
        </div>
      </div>

      {/* ── Stat cards ── */}
      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={12} sm={6}>
          <StatCard
            title="规则总数"
            value={stats?.total_rules ?? '-'}
            icon={<SafetyOutlined />}
            loading={statsLoading}
          />
        </Col>
        <Col xs={12} sm={6}>
          <StatCard
            title="总命中次数"
            value={effectiveness.reduce((s, r) => s + r.hit_count, 0)}
            icon={<ThunderboltOutlined />}
            loading={effLoading}
          />
        </Col>
        <Col xs={12} sm={6}>
          <StatCard
            title="审查报告数"
            value={totalReports || '-'}
            icon={<TagsOutlined />}
            loading={effLoading}
          />
        </Col>
        <Col xs={12} sm={6}>
          <StatCard
            title="平均命中率"
            value={
              effectiveness.length > 0
                ? `${Math.round(effectiveness.reduce((s, r) => s + r.hit_rate, 0) / effectiveness.length * 100)}%`
                : '-'
            }
            icon={<WarningOutlined />}
            loading={effLoading}
          />
        </Col>
      </Row>

      {/* ── Breakdown cards ── */}
      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={24} sm={8}>
          <Card title="按类型分布" size="small" loading={statsLoading} style={{ borderRadius: 10 }}>
            {stats?.by_type && Object.keys(stats.by_type).length > 0 ? (
              <BreakdownTags data={stats.by_type} colorMap={TYPE_COLORS} labelFn={typeLabel} />
            ) : (
              <Text type="secondary">暂无数据</Text>
            )}
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card title="按分类分布" size="small" loading={statsLoading} style={{ borderRadius: 10 }}>
            {stats?.by_category && Object.keys(stats.by_category).length > 0 ? (
              <BreakdownTags data={stats.by_category} labelFn={categoryLabel} />
            ) : (
              <Text type="secondary">暂无数据</Text>
            )}
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card title="按风险级别分布" size="small" loading={statsLoading} style={{ borderRadius: 10 }}>
            {stats?.by_risk && Object.keys(stats.by_risk).length > 0 ? (
              <BreakdownTags data={stats.by_risk} colorMap={RISK_COLORS} />
            ) : (
              <Text type="secondary">暂无数据</Text>
            )}
          </Card>
        </Col>
      </Row>

      {/* ── Effectiveness table ── */}
      <Card
        title="规则效力排行"
        size="small"
        loading={effLoading}
        style={{ borderRadius: 10 }}
        extra={
          <Text type="secondary" style={{ fontSize: 12 }}>
            共 {effectiveness.length} 条 · 覆盖 {totalReports} 份报告
          </Text>
        }
      >
        {effectiveness.length === 0 && !effLoading ? (
          <Empty
            description="暂无效力数据"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        ) : (
          <Table
            dataSource={effectiveness}
            rowKey="rule_id"
            size="small"
            pagination={{ pageSize: 15, showSizeChanger: false }}
            columns={[
              {
                title: '规则 ID',
                dataIndex: 'rule_id',
                key: 'rule_id',
                width: 140,
                ellipsis: true,
              },
              {
                title: '描述',
                dataIndex: 'description',
                key: 'description',
                ellipsis: true,
              },
              {
                title: '命中次数',
                dataIndex: 'hit_count',
                key: 'hit_count',
                width: 100,
                sorter: (a, b) => a.hit_count - b.hit_count,
                defaultSortOrder: 'descend',
              },
              {
                title: '覆盖报告',
                dataIndex: 'total_reports',
                key: 'total_reports',
                width: 100,
              },
              {
                title: '命中率',
                dataIndex: 'hit_rate',
                key: 'hit_rate',
                width: 100,
                sorter: (a, b) => a.hit_rate - b.hit_rate,
                render: (v: number) => {
                  const pct = Math.round(v * 100)
                  let color = '#16a34a'
                  if (pct < 30) color = '#dc2626'
                  else if (pct < 60) color = '#eab308'
                  return (
                    <Tag color={color === '#dc2626' ? 'red' : color === '#eab308' ? 'gold' : 'green'}>
                      {pct}%
                    </Tag>
                  )
                },
              },
            ]}
          />
        )}
      </Card>
    </div>
  )
}

export default RulesDashboard
