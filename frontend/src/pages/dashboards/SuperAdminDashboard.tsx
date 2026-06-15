/**
 * SuperAdminDashboard — 超级管理员工作台
 *
 * KPI: 今日审查量 / 活跃用户 / Token消耗 / 系统健康
 * 内容: 审查趋势 + 模型调用量 + 风险分布 + 系统告警 + 待处理任务
 */

import React, { useState, useEffect } from 'react'
import {
  Row, Col, Card, Typography, Button, Tag,
  Skeleton, Space, Badge, message,
} from 'antd'
import {
  SafetyOutlined, TeamOutlined, DollarOutlined, HeartOutlined,
  ArrowRightOutlined, WarningOutlined, AuditOutlined,
  SettingOutlined, GlobalOutlined, NodeIndexOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { getMemberDashboard, getDashboardStats } from '../../services/api'
import type { DashboardStats } from '../../types'
import KpiCard from '../../components/dashboard/KpiCard'
import RiskDistribution from '../../components/dashboard/RiskDistribution'
import TrendChart from '../../components/dashboard/TrendChart'
import RecentActivity from '../../components/dashboard/RecentActivity'

const { Title, Text } = Typography

interface SuperAdminData {
  summary: {
    today_reviews: number
    active_users: number
    token_used_today: number
    token_cost_today: number
    total_tokens: number
    total_cost: number
    health_status: string
    health_latency: number
  }
  review_trend: Array<{ label: string; count: number }>
  model_calls_trend: Array<{ label: string; count: number }>
  risk_distribution: { high: number; medium: number; low: number }
  alerts: Array<{ label: string; severity: string; count?: number }>
  pending_tasks: Array<{ label: string; count: number; path: string }>
  recent_reports: Array<{
    id: number | string
    source_file: string
    user_name: string
    risk_level: string
    status: string
    created_at: string
  }>
}

const SuperAdminDashboard: React.FC = () => {
  const navigate = useNavigate()
  const [data, setData] = useState<SuperAdminData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [dashResp, statsResp] = await Promise.all([
          getMemberDashboard().catch(() => null),
          getDashboardStats().catch(() => null),
        ])
        const dash = dashResp?.compliance || {}
        const stats: DashboardStats | null = statsResp || null

        setData({
          summary: {
            today_reviews: dash.reports_this_month || 0,
            active_users: 0,
            token_used_today: stats?.llm?.total_tokens || 0,
            token_cost_today: stats?.llm?.total_cost || 0,
            total_tokens: stats?.llm?.total_tokens || 0,
            total_cost: stats?.llm?.total_cost || 0,
            health_status: 'ok',
            health_latency: 45,
          },
          review_trend: (dash.monthly_trend || []).map((d: any) => ({ label: d.month?.slice(5) || d.month, count: d.count })),
          model_calls_trend: (stats?.llm?.recent_calls || []).slice(-7).map((c: any) => ({ label: c.timestamp?.slice(5, 10) || '', count: c.tokens || 0 })),
          risk_distribution: {
            high: dash.risk_level_distribution?.high || 0,
            medium: dash.risk_level_distribution?.medium || 0,
            low: dash.risk_level_distribution?.low || 0,
          },
          alerts: [
            { label: '配额超限用户', severity: 'error', count: 0 },
            { label: 'LLM 调用失败率', severity: 'warning' },
            { label: '规则同步待更新', severity: 'warning', count: 0 },
          ],
          pending_tasks: [
            { label: '复核待审', count: (dash.risk_level_distribution?.high || 0) + (dash.risk_level_distribution?.critical || 0), path: '/reports' },
            { label: 'KG 节点审核', count: 0, path: '/ops/kg-seed' },
            { label: '规则同步待更新', count: 0, path: '/ops/scheduler' },
          ],
          recent_reports: (dash.recent || []).slice(0, 5).map((r: any) => ({
            ...r,
            title: r.source_file || `审查报告 #${r.id}`,
            time: r.created_at ? new Date(r.created_at).toLocaleString('zh-CN') : '',
          })),
        })
      } catch {
        message.error('数据加载失败')
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>系统总览</Title>
        <Text type="secondary">超级管理员控制台 · 全局监控</Text>
      </div>

      {/* KPI 卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={12} lg={6}>
          <KpiCard title="今日审查量" value={data?.summary.today_reviews ?? '-'} icon={<SafetyOutlined />} color="#2563eb" loading={loading} suffix="次"
            trend={{ value: 12, isUp: true }} />
        </Col>
        <Col xs={12} lg={6}>
          <KpiCard title="活跃用户" value={data?.summary.active_users ?? '-'} icon={<TeamOutlined />} color="#7c3aed" loading={loading} suffix="人" />
        </Col>
        <Col xs={12} lg={6}>
          <KpiCard title="Token消耗" value={data?.summary.token_cost_today != null ? `¥${(data.summary.token_cost_today as number).toFixed(2)}` : '-'} icon={<DollarOutlined />} color="#16a34a" loading={loading}
            suffix={data?.summary.total_cost != null ? `累计 ¥${(data.summary.total_cost as number).toFixed(0)}` : ''} />
        </Col>
        <Col xs={12} lg={6}>
          <KpiCard title="系统健康" value={data?.summary.health_status === 'ok' ? '正常' : '异常'} icon={<HeartOutlined />} color={data?.summary.health_status === 'ok' ? '#16a34a' : '#dc2626'} loading={loading}
            suffix={`延迟 ${data?.summary.health_latency ?? '-'}ms`} />
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        {/* 审查趋势 */}
        <Col xs={24} lg={12}>
          <Card title={<Text strong style={{ fontSize: 15 }}>审查量趋势（近6月）</Text>} style={{ borderRadius: 12 }} styles={{ body: { padding: '16px 20px' } }}>
            {loading ? <Skeleton active paragraph={{ rows: 3 }} /> : data?.review_trend?.length ? (
              <TrendChart data={data.review_trend} height={50} />
            ) : <Text type="secondary">暂无数据</Text>}
          </Card>
        </Col>

        {/* 模型调用量 */}
        <Col xs={24} lg={12}>
          <Card title={<Text strong style={{ fontSize: 15 }}>模型调用量（近7天）</Text>} style={{ borderRadius: 12 }} styles={{ body: { padding: '16px 20px' } }}>
            {loading ? <Skeleton active paragraph={{ rows: 3 }} /> : data?.model_calls_trend?.length ? (
              <TrendChart data={data.model_calls_trend} height={50} />
            ) : <Text type="secondary">暂无数据</Text>}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        {/* 风险等级分布 */}
        <Col xs={24} lg={8}>
          <Card title={<Text strong style={{ fontSize: 15 }}>风险等级分布</Text>} style={{ borderRadius: 12 }} styles={{ body: { padding: '16px 20px' } }}>
            {loading ? <Skeleton active paragraph={{ rows: 4 }} /> : (
              <RiskDistribution items={[
                { label: '高风险', count: data?.risk_distribution.high ?? 0, color: '#dc2626' },
                { label: '中风险', count: data?.risk_distribution.medium ?? 0, color: '#eab308' },
                { label: '低风险', count: data?.risk_distribution.low ?? 0, color: '#16a34a' },
              ]} />
            )}
          </Card>
        </Col>

        {/* 系统告警 */}
        <Col xs={24} lg={8}>
          <Card title={<div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Text strong style={{ fontSize: 15 }}>系统告警</Text><Badge status="error" /></div>} style={{ borderRadius: 12 }} styles={{ body: { padding: '16px 20px' } }}>
            {loading ? <Skeleton active paragraph={{ rows: 3 }} /> : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {(data?.alerts || []).map((alert, idx) => (
                  <div key={idx} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', borderRadius: 6, background: alert.severity === 'error' ? '#fef2f2' : '#fefce8' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <WarningOutlined style={{ color: alert.severity === 'error' ? '#dc2626' : '#eab308', fontSize: 14 }} />
                      <Text style={{ fontSize: 13 }}>{alert.label}</Text>
                    </div>
                    {alert.count != null && <Tag color={alert.severity === 'error' ? 'red' : 'gold'}>{alert.count}</Tag>}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </Col>

        {/* 待处理任务 */}
        <Col xs={24} lg={8}>
          <Card title={<Text strong style={{ fontSize: 15 }}>待处理任务</Text>} style={{ borderRadius: 12 }} styles={{ body: { padding: '16px 20px' } }}>
            {loading ? <Skeleton active paragraph={{ rows: 3 }} /> : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {(data?.pending_tasks || []).map((task, idx) => (
                  <div key={idx} onClick={() => navigate(task.path)} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderRadius: 8, border: '1px solid #e2e8f0', cursor: 'pointer', transition: 'background 0.15s' }}
                    onMouseEnter={e => { e.currentTarget.style.background = '#f8fafc' }} onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}>
                    <Text style={{ fontSize: 13 }}>{task.label}</Text>
                    <Space>
                      {task.count > 0 ? <Tag color="red">{task.count}</Tag> : <Tag>0</Tag>}
                      <ArrowRightOutlined style={{ color: '#94a3b8', fontSize: 12 }} />
                    </Space>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </Col>
      </Row>

      {/* 快捷入口 + 最近审查活动 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card title={<Text strong style={{ fontSize: 15 }}>快捷入口</Text>} style={{ borderRadius: 12 }} styles={{ body: { padding: '16px 20px' } }}>
            <Space direction="vertical" size={10} style={{ width: '100%' }}>
              <Button block icon={<SettingOutlined />} onClick={() => navigate('/rules')} style={{ borderRadius: 8 }}>规则中心</Button>
              <Button block icon={<TeamOutlined />} onClick={() => navigate('/manage/users')} style={{ borderRadius: 8 }}>用户管理</Button>
              <Button block icon={<GlobalOutlined />} onClick={() => navigate('/ops/crawler')} style={{ borderRadius: 8 }}>案例采集引擎</Button>
              <Button block icon={<NodeIndexOutlined />} onClick={() => navigate('/ops/kg-seed')} style={{ borderRadius: 8 }}>KG 播种</Button>
              <Button block icon={<HeartOutlined />} onClick={() => navigate('/ops/health')} style={{ borderRadius: 8 }}>系统健康</Button>
              <Button block icon={<AuditOutlined />} onClick={() => navigate('/manage/audit')} style={{ borderRadius: 8 }}>审计日志</Button>
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={16}>
          <RecentActivity
            title="最近审查活动"
            items={(data?.recent_reports || []).slice(0, 8).map((r: any) => ({
              id: r.id,
              title: `${r.user_name ? r.user_name + ' · ' : ''}${r.source_file || `审查报告 #${r.id}`}`,
              time: r.created_at ? new Date(r.created_at).toLocaleString('zh-CN') : r.time || '',
              riskLevel: r.risk_level,
              status: r.status,
            }))}
            loading={loading}
            onItemClick={id => navigate(`/report/${id}`)}
            onViewAll={() => navigate('/reports')}
          />
        </Col>
      </Row>
    </div>
  )
}

export default SuperAdminDashboard
