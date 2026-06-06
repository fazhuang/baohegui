import React, { useState, useEffect } from 'react'
import {
  Row, Col, Card, Typography, Button, Tag,
  Skeleton, Space, Tooltip, Empty, message,
} from 'antd'
import {
  UploadOutlined, HistoryOutlined, FileSearchOutlined,
  ArrowRightOutlined, CheckCircleOutlined, SafetyOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'

const { Title, Text, Paragraph } = Typography

// ── 类型定义 ────────────────────────────────────────────────

interface DashboardData {
  summary: {
    total_reports: number
    reports_this_month: number
    passed_count: number
    failed_count: number
    pass_rate: number
    risk_level_distribution: { critical: number; high: number; medium: number; low: number }
  }
  recent_reports: Array<{
    id: number | string
    source_file: string
    status: string
    risk_level: string
    created_at: string
    risk_level_cn: string
  }>
  announcements: Array<{
    id: number
    title: string
    severity: string
    category: string
    case_date: string
    summary: string
    source: string
  }>
  monthly_trend: Array<{ month: string; count: number }>
}

// ── 风险等级颜色映射 ────────────────────────────────────────

const RISK_COLORS: Record<string, string> = {
  critical: '#dc2626',
  high: '#ea580c',
  medium: '#eab308',
  low: '#16a34a',
  pass: '#2563eb',
}

const SEVERITY_COLORS: Record<string, { border: string; bg: string; text: string; label: string }> = {
  critical: { border: '#dc2626', bg: '#fef2f2', text: '#991b1b', label: '严重' },
  danger: { border: '#ea580c', bg: '#fff7ed', text: '#9a3412', label: '高风险' },
  warning: { border: '#eab308', bg: '#fefce8', text: '#854d0e', label: '警示' },
  info: { border: '#2563eb', bg: '#eff6ff', text: '#1e40af', label: '信息' },
}

// ── 趋势迷你图 ──────────────────────────────────────────────

const MiniTrendBar: React.FC<{ data: Array<{ month: string; count: number }> }> = ({ data }) => {
  const max = Math.max(...data.map(d => d.count), 1)
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 40, paddingTop: 4 }}>
      {data.map((d, i) => (
        <Tooltip key={i} title={`${d.month}: ${d.count} 次`}>
          <div
            style={{
              width: 12,
              height: `${Math.max((d.count / max) * 100, 4)}%`,
              background: d.count > 0 ? 'var(--color-action)' : 'var(--color-border)',
              borderRadius: '3px 3px 0 0',
              transition: 'height 0.3s ease',
              cursor: 'pointer',
              minHeight: 4,
            }}
          />
        </Tooltip>
      ))}
    </div>
  )
}

// ── 通过率环形指示器 ────────────────────────────────────────

const PassRateRing: React.FC<{ rate: number }> = ({ rate }) => {
  const radius = 36
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (rate / 100) * circumference
  const isHigh = rate >= 80

  return (
    <div style={{ position: 'relative', width: 90, height: 90, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <svg width="90" height="90" viewBox="0 0 90 90" style={{ position: 'absolute' }}>
        <circle
          cx="45" cy="45" r={radius}
          fill="none"
          stroke="var(--color-border-light)"
          strokeWidth="8"
        />
        <circle
          cx="45" cy="45" r={radius}
          fill="none"
          stroke={isHigh ? 'var(--color-success)' : 'var(--color-warning)'}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform="rotate(-90 45 45)"
          style={{ transition: 'stroke-dashoffset 0.8s ease' }}
        />
      </svg>
      <Text strong style={{ fontSize: 18, color: isHigh ? 'var(--color-success)' : 'var(--color-warning)' }}>
        {rate}%
      </Text>
    </div>
  )
}

// ── KPI 统计卡片 ────────────────────────────────────────────

interface KpiCardProps {
  title: string
  value: number | string
  icon: React.ReactNode
  color: string
  bgColor: string
  suffix?: string
  loading: boolean
}

const KpiCard: React.FC<KpiCardProps> = ({ title, value, icon, color, bgColor, suffix, loading }) => (
  <Card
    className="kpi-card"
    style={{ borderRadius: 12, border: '1px solid var(--color-border)', height: '100%' }}
    styles={{ body: { padding: '20px 24px' } }}
  >
    {loading ? (
      <Skeleton active paragraph={{ rows: 1 }} />
    ) : (
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <Text type="secondary" style={{ fontSize: 13 }}>{title}</Text>
          <div style={{ marginTop: 4, display: 'flex', alignItems: 'baseline', gap: 4 }}>
            <span style={{ fontSize: 28, fontWeight: 700, color: 'var(--color-text)', lineHeight: 1 }}>
              {value}
            </span>
            {suffix && <Text type="secondary" style={{ fontSize: 14 }}>{suffix}</Text>}
          </div>
        </div>
        <div
          style={{
            width: 44, height: 44, borderRadius: 10,
            background: bgColor,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color,
            fontSize: 22,
          }}
        >
          {icon}
        </div>
      </div>
    )}
  </Card>
)

// ── 公告卡片 ────────────────────────────────────────────────

interface AnnouncementCardProps {
  id: number
  title: string
  severity: string
  category: string
  caseDate: string
  summary: string
  source: string
}

const AnnouncementCard: React.FC<AnnouncementCardProps> = ({
  title, severity, caseDate, summary, source,
}) => {
  const sc = SEVERITY_COLORS[severity] || SEVERITY_COLORS.info
  return (
    <div
      className="announcement-item"
      style={{
        padding: '12px 16px',
        borderLeft: `3px solid ${sc.border}`,
        background: sc.bg,
        borderRadius: '0 var(--border-radius) var(--border-radius) 0',
        marginBottom: 10,
        cursor: 'pointer',
        transition: 'box-shadow 0.2s',
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLElement).style.boxShadow = '0 2px 8px rgba(0,0,0,0.06)'
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.boxShadow = 'none'
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0 }}>
          <Tag
            color={severity === 'critical' ? 'red' : severity === 'danger' ? 'orange' : severity === 'warning' ? 'gold' : 'blue'}
            style={{ margin: 0, fontSize: 11 }}
          >
            {sc.label}
          </Tag>
          <Text style={{ fontSize: 13, fontWeight: 600, flex: 1 }} ellipsis>
            {title}
          </Text>
        </div>
        <Text type="secondary" style={{ fontSize: 11, whiteSpace: 'nowrap', marginLeft: 8 }}>
          {caseDate}
        </Text>
      </div>
      <Paragraph type="secondary" style={{ fontSize: 12, lineHeight: 1.5, margin: 0 }} ellipsis={{ rows: 2 }}>
        {summary}
      </Paragraph>
      {source && (
        <Text type="secondary" style={{ fontSize: 10, marginTop: 4, display: 'block' }}>
          来源：{source}
        </Text>
      )}
    </div>
  )
}

// ── 快捷操作按钮 ────────────────────────────────────────────

const QuickAction: React.FC<{
  icon: React.ReactNode
  label: string
  description: string
  onClick: () => void
  primary?: boolean
}> = ({ icon, label, description, onClick, primary }) => (
  <div
    onClick={onClick}
    style={{
      display: 'flex',
      alignItems: 'center',
      gap: 14,
      padding: '14px 18px',
      borderRadius: 10,
      border: primary ? '1px solid var(--color-action)' : '1px solid var(--color-border)',
      background: primary ? 'var(--color-brand-light)' : 'var(--color-bg-card)',
      cursor: 'pointer',
      transition: 'all 0.2s',
    }}
    onMouseEnter={(e) => {
      const t = e.currentTarget
      t.style.transform = 'translateY(-2px)'
      t.style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)'
    }}
    onMouseLeave={(e) => {
      const t = e.currentTarget
      t.style.transform = 'translateY(0)'
      t.style.boxShadow = 'none'
    }}
  >
    <div style={{
      width: 42, height: 42, borderRadius: 10,
      background: primary ? 'var(--color-action)' : 'var(--color-brand-light)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: primary ? '#fff' : 'var(--color-action)', fontSize: 20,
    }}>
      {icon}
    </div>
    <div style={{ flex: 1 }}>
      <Text strong style={{ fontSize: 14 }}>{label}</Text>
      <br />
      <Text type="secondary" style={{ fontSize: 12 }}>{description}</Text>
    </div>
    <ArrowRightOutlined style={{ color: 'var(--color-text-tertiary)', fontSize: 14 }} />
  </div>
)

// ── 主组件 ──────────────────────────────────────────────────

const DashboardPage: React.FC = () => {
  const navigate = useNavigate()
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const token = localStorage.getItem('token')
        if (!token) return

        // 并行获取仪表盘数据和公告
        const [dashResp, annResp] = await Promise.all([
          axios.get('/api/member/dashboard', {
            headers: { Authorization: `Bearer ${token}` },
          }).catch(() => null),
          axios.get('/api/announcements', {
            params: { limit: 5 },
            headers: { Authorization: `Bearer ${token}` },
          }).catch(() => null),
        ])

        const dash = dashResp?.data
        const ann = annResp?.data

        setData({
          summary: dash?.compliance || {
            total_reports: 0,
            reports_this_month: 0,
            passed_count: 0,
            failed_count: 0,
            pass_rate: 0,
            risk_level_distribution: { critical: 0, high: 0, medium: 0, low: 0 },
          },
          recent_reports: dash?.compliance?.recent || [],
          announcements: ann?.announcements || [],
          monthly_trend: dash?.compliance?.monthly_trend || [],
        })
      } catch {
        message.error('数据加载失败，请检查网络连接')
        // 后端未就绪时静默使用空数据
        if (!data) {
          setData({
            summary: { total_reports: 0, reports_this_month: 0, passed_count: 0, failed_count: 0, pass_rate: 0, risk_level_distribution: { critical: 0, high: 0, medium: 0, low: 0 } },
            recent_reports: [],
            announcements: [],
            monthly_trend: [],
          })
        }
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  // ── 当没有真实公告数据时，使用静态警示案例 ──
  const announcements = (data?.announcements?.length ? data.announcements : null)

  return (
    <div className="dashboard-page">
      {/* ── 页面标题 ── */}
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>
          工作台
        </Title>
        <Text type="secondary">招标文件合规自检 · 发布前审查</Text>
      </div>

      {/* ── KPI 统计卡片 ── */}
      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={12} sm={12} lg={6}>
          <KpiCard
            title="本月审查次数"
            value={data?.summary.reports_this_month ?? '-'}
            icon={<SafetyOutlined />}
            color="#2563eb"
            bgColor="#eff6ff"
            loading={loading}
            suffix="次"
          />
        </Col>
        <Col xs={12} sm={12} lg={6}>
          <KpiCard
            title="累计审查次数"
            value={data?.summary.total_reports ?? '-'}
            icon={<FileSearchOutlined />}
            color="#7c3aed"
            bgColor="#f5f3ff"
            loading={loading}
            suffix="次"
          />
        </Col>
        <Col xs={12} sm={12} lg={6}>
          <KpiCard
            title="通过率"
            value={data?.summary.pass_rate ?? '-'}
            icon={<CheckCircleOutlined />}
            color="#16a34a"
            bgColor="#f0fdf4"
            loading={loading}
            suffix="%"
          />
        </Col>
        <Col xs={12} sm={12} lg={6}>
          <KpiCard
            title="待处理高风险"
            value={data?.summary.risk_level_distribution?.critical
              ? data.summary.risk_level_distribution.critical + data.summary.risk_level_distribution.high
              : '-'}
            icon={<WarningOutlined />}
            color="#dc2626"
            bgColor="#fef2f2"
            loading={loading}
            suffix="项"
          />
        </Col>
      </Row>

      {/* ── 快速操作 + 趋势 ── */}
      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={24} lg={12}>
          <Card
            title={<Text strong style={{ fontSize: 15 }}>快速操作</Text>}
            style={{ borderRadius: 12, height: '100%' }}
            styles={{ body: { padding: '16px 20px' } }}
          >
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <QuickAction
                icon={<UploadOutlined />}
                label="新建合规审查"
                description="上传招标文件进行合规自检"
                onClick={() => navigate('/upload')}
                primary
              />
              <QuickAction
                icon={<HistoryOutlined />}
                label="查看历史记录"
                description="浏览过往审查结果和报告"
                onClick={() => navigate('/history')}
              />
            </Space>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card
            title={
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Text strong style={{ fontSize: 15 }}>审查趋势（近6月）</Text>
                {loading ? null : (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    共 {data?.monthly_trend?.reduce((s, d) => s + d.count, 0) ?? 0} 次
                  </Text>
                )}
              </div>
            }
            style={{ borderRadius: 12, height: '100%' }}
            styles={{ body: { padding: '16px 20px' } }}
          >
            {loading ? (
              <Skeleton active paragraph={{ rows: 3 }} />
            ) : data?.monthly_trend?.length ? (
              <div>
                <MiniTrendBar data={data.monthly_trend} />
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
                  {data.monthly_trend.map((d, i) => (
                    <Text key={i} type="secondary" style={{ fontSize: 10 }}>{d.month.slice(5)}</Text>
                  ))}
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 80 }}>
                <Text type="secondary">暂无趋势数据</Text>
              </div>
            )}

            {/* 通过率环形图 */}
            {!loading && data?.summary.pass_rate !== undefined && (
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 16, marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--color-border)' }}>
                <PassRateRing rate={data.summary.pass_rate} />
                <div>
                  <Text strong style={{ fontSize: 15 }}>审查通过率</Text>
                  <br />
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    {data.summary.passed_count} 通过 / {data.summary.failed_count} 未通过
                  </Text>
                </div>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      {/* ── 最近审查 + 警示公告 ── */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card
            title={<Text strong style={{ fontSize: 15 }}>最近审查</Text>}
            extra={
              <Button type="link" size="small" onClick={() => navigate('/history')}>
                查看全部 <ArrowRightOutlined />
              </Button>
            }
            style={{ borderRadius: 12, height: '100%' }}
            styles={{ body: { padding: '8px 16px 16px' } }}
          >
            {loading ? (
              <Skeleton active paragraph={{ rows: 4 }} />
            ) : data?.recent_reports?.length ? (
              <div style={{ maxHeight: 320, overflowY: 'auto' }}>
                {data.recent_reports.slice(0, 5).map((r, idx) => {
                  const rl = r.risk_level || 'low'
                  return (
                    <div
                      key={idx}
                      onClick={() => navigate(`/report/${r.id}`)}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '10px 12px',
                        borderRadius: 8,
                        cursor: 'pointer',
                        transition: 'background 0.15s',
                      }}
                      onMouseEnter={(e) => {
                        (e.currentTarget as HTMLElement).style.background = 'var(--color-bg)'
                      }}
                      onMouseLeave={(e) => {
                        (e.currentTarget as HTMLElement).style.background = 'transparent'
                      }}
                    >
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <Text style={{ fontSize: 13 }} ellipsis>
                          {r.source_file || `审查报告 #${r.id}`}
                        </Text>
                        <br />
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {r.created_at ? new Date(r.created_at).toLocaleString('zh-CN') : ''}
                        </Text>
                      </div>
                      <Tag
                        color={rl === 'pass' ? 'green' : rl === 'critical' ? 'red' : rl === 'high' ? 'orange' : rl === 'medium' ? 'gold' : 'blue'}
                        style={{ margin: 0, fontSize: 11 }}
                      >
                        {r.risk_level_cn || rl}
                      </Tag>
                    </div>
                  )
                })}
              </div>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无审查记录"
                style={{ padding: '24px 0' }}
              >
                <Button type="primary" icon={<UploadOutlined />} onClick={() => navigate('/upload')}>
                  开始第一次审查
                </Button>
              </Empty>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card
            title={
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Text strong style={{ fontSize: 15 }}>警示公告</Text>
                <Tag color="red" style={{ fontSize: 10 }}>实时</Tag>
              </div>
            }
            style={{ borderRadius: 12, height: '100%' }}
            styles={{ body: { padding: '8px 16px 16px', maxHeight: 420, overflowY: 'auto' } }}
          >
            {loading ? (
              <Skeleton active paragraph={{ rows: 4 }} />
            ) : announcements ? (
              announcements.map((a) => (
                <AnnouncementCard
                  key={a.id}
                  id={a.id}
                  title={a.title}
                  severity={a.severity}
                  category={a.category}
                  caseDate={a.case_date}
                  summary={a.summary}
                  source={a.source}
                />
              ))
            ) : (
              <>
                {/* 静态警示案例（后端未就绪时的默认展示） */}
                <AnnouncementCard
                  id={1}
                  title="甘肃省政府采购网：关于某建设工程咨询有限公司提供虚假材料谋取中标的行政处罚通报"
                  severity="danger"
                  category="违规处罚"
                  caseDate="2026-06-02"
                  summary="经省财政厅大数据比对核查，涉事供应商在参与省直机关综合办公楼维修改造项目投标中，伪造一级建造师执业资格证书及相关社保缴纳证明，情节严重。"
                  source="甘肃省政府采购网"
                />
                <AnnouncementCard
                  id={2}
                  title="中国政府采购网：某信息技术服务商涉嫌串通投标行为的立案查处公示"
                  severity="critical"
                  category="违规处罚"
                  caseDate="2026-05-28"
                  summary="在智慧政务云平台二期建设项目评标过程中，专家评审组发现三家投标单位的电子投标文件由同一台电脑终端（MAC地址一致）加密上传，存在串通投标行为。"
                  source="中国政府采购网"
                />
                <AnnouncementCard
                  id={3}
                  title="甘肃省公共资源交易局：关于某建筑工程局有限公司违规转包项目的不良行为记录"
                  severity="warning"
                  category="违规处罚"
                  caseDate="2026-05-25"
                  summary="涉事建筑企业在中标省道提升改造标段后，擅自将主体结构工程肢解转包给无资质的劳务施工队，引发质量安全隐患。"
                  source="甘肃省公共资源交易网"
                />
              </>
            )}
          </Card>
        </Col>
      </Row>

      {/* ── 风险分布概览 ── */}
      {!loading && data?.summary?.risk_level_distribution && (
        <Row gutter={[16, 16]} style={{ marginTop: 20 }}>
          <Col span={24}>
            <Card
              title={<Text strong style={{ fontSize: 15 }}>风险等级分布</Text>}
              style={{ borderRadius: 12 }}
              styles={{ body: { padding: '16px 20px' } }}
            >
              <Row gutter={16}>
                {[
                  { label: '严重', level: 'critical', count: data.summary.risk_level_distribution.critical },
                  { label: '高风险', level: 'high', count: data.summary.risk_level_distribution.high },
                  { label: '中风险', level: 'medium', count: data.summary.risk_level_distribution.medium },
                  { label: '低风险', level: 'low', count: data.summary.risk_level_distribution.low },
                ].map(({ label, level, count }) => {
                  const total = Object.values(data.summary.risk_level_distribution).reduce((s: number, v: number) => s + v, 0)
                  const pct = total > 0 ? Math.round((count / total) * 100) : 0
                  return (
                    <Col xs={12} sm={6} key={level} style={{ marginBottom: 12 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                        <div style={{
                          width: 10, height: 10, borderRadius: 3,
                          background: RISK_COLORS[level] || '#94a3b8',
                        }} />
                        <Text style={{ fontSize: 13 }}>{label}</Text>
                        <Text strong style={{ fontSize: 16, marginLeft: 'auto' }}>{count}</Text>
                      </div>
                      <div style={{
                        height: 6, borderRadius: 3,
                        background: 'var(--color-border-light)',
                        overflow: 'hidden',
                      }}>
                        <div style={{
                          height: '100%',
                          width: `${pct}%`,
                          background: RISK_COLORS[level] || '#94a3b8',
                          borderRadius: 3,
                          transition: 'width 0.6s ease',
                        }} />
                      </div>
                    </Col>
                  )
                })}
              </Row>
            </Card>
          </Col>
        </Row>
      )}
    </div>
  )
}

export default DashboardPage
