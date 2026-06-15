/**
 * AdminDashboard — 普通管理员工作台
 *
 * KPI: 待审文件 / 今日审查量 / 审查通过率 / 待复核数
 * 内容: 风险等级统计 + 待处理任务 + 快捷操作 + 最近审查活动
 */

import React, { useState, useEffect } from 'react'
import {
  Row, Col, Card, Typography, Button, Tag,
  Skeleton, Space, message,
} from 'antd'
import {
  FileSearchOutlined, CheckCircleOutlined, WarningOutlined,
  ArrowRightOutlined, SafetyOutlined, AuditOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import KpiCard from '../../components/dashboard/KpiCard'
import RiskDistribution from '../../components/dashboard/RiskDistribution'
import RecentActivity from '../../components/dashboard/RecentActivity'

const { Title, Text } = Typography

interface AdminData {
  summary: {
    pending_count: number
    today_count: number
    pass_rate: number
    needs_review: number
    total_reports: number
    passed_count: number
    failed_count: number
  }
  risk_distribution: { high: number; medium: number; low: number }
  recent_reports: Array<{
    id: number | string
    source_file: string
    user_name: string
    risk_level: string
    status: string
    created_at: string
  }>
  pending_tasks: Array<{ label: string; count: number; path: string }>
}

const AdminDashboard: React.FC = () => {
  const navigate = useNavigate()
  const [data, setData] = useState<AdminData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const token = localStorage.getItem('token')
        if (!token) return
        const [dashResp] = await Promise.all([
          axios.get('/api/member/dashboard', { headers: { Authorization: `Bearer ${token}` } }).catch(() => null),
        ])
        const dash = dashResp?.data?.compliance || {}
        setData({
          summary: {
            pending_count: dash.reports_this_month || 0,
            today_count: dash.reports_this_month || 0,
            pass_rate: dash.pass_rate || 0,
            needs_review: (dash.risk_level_distribution?.high || 0) + (dash.risk_level_distribution?.critical || 0),
            total_reports: dash.total_reports || 0,
            passed_count: dash.passed_count || 0,
            failed_count: dash.failed_count || 0,
          },
          risk_distribution: {
            high: dash.risk_level_distribution?.high || 0,
            medium: dash.risk_level_distribution?.medium || 0,
            low: dash.risk_level_distribution?.low || 0,
          },
          recent_reports: (dash.recent || []).map((r: any) => ({
            ...r,
            title: r.source_file || `审查报告 #${r.id}`,
            time: r.created_at ? new Date(r.created_at).toLocaleString('zh-CN') : '',
          })),
          pending_tasks: [
            { label: '待复核报告', count: (dash.risk_level_distribution?.high || 0) + (dash.risk_level_distribution?.critical || 0), path: '/reports' },
            { label: '反馈待处理', count: 0, path: '/reports/feedback' },
          ],
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
        <Title level={3} style={{ margin: 0 }}>工作台</Title>
        <Text type="secondary">管理员概览 · 招标文件合规自检系统</Text>
      </div>

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={12} lg={6}><KpiCard title="待审文件" value={data?.summary.pending_count ?? '-'} icon={<FileSearchOutlined />} color="#2563eb" loading={loading} suffix="份" /></Col>
        <Col xs={12} lg={6}><KpiCard title="今日审查量" value={data?.summary.today_count ?? '-'} icon={<SafetyOutlined />} color="#7c3aed" loading={loading} suffix="次" /></Col>
        <Col xs={12} lg={6}><KpiCard title="审查通过率" value={data?.summary.pass_rate ?? '-'} icon={<CheckCircleOutlined />} color="#16a34a" loading={loading} suffix="%" /></Col>
        <Col xs={12} lg={6}><KpiCard title="待复核数" value={data?.summary.needs_review ?? '-'} icon={<AuditOutlined />} color="#dc2626" loading={loading} suffix="项" /></Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={24} lg={8}>
          <Card title={<Text strong style={{ fontSize: 15 }}>风险等级统计（本月）</Text>} style={{ borderRadius: 12, height: '100%' }} styles={{ body: { padding: '16px 20px' } }}>
            {loading ? <Skeleton active paragraph={{ rows: 4 }} /> : (
              <RiskDistribution items={[
                { label: '高风险', count: data?.risk_distribution.high ?? 0, color: '#dc2626' },
                { label: '中风险', count: data?.risk_distribution.medium ?? 0, color: '#eab308' },
                { label: '低风险', count: data?.risk_distribution.low ?? 0, color: '#16a34a' },
              ]} />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title={<Text strong style={{ fontSize: 15 }}>待处理任务</Text>} style={{ borderRadius: 12, height: '100%' }} styles={{ body: { padding: '16px 20px' } }}>
            {loading ? <Skeleton active paragraph={{ rows: 3 }} /> : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {(data?.pending_tasks || []).map((task, idx) => (
                  <div key={idx} onClick={() => navigate(task.path)}
                    style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderRadius: 8, border: '1px solid #e2e8f0', cursor: 'pointer', transition: 'background 0.15s' }}
                    onMouseEnter={e => { e.currentTarget.style.background = '#f8fafc' }} onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{ width: 8, height: 8, borderRadius: '50%', background: task.count > 0 ? '#dc2626' : '#94a3b8' }} />
                      <Text style={{ fontSize: 13 }}>{task.label}</Text>
                    </div>
                    <Space>{task.count > 0 && <Tag color="red">{task.count}</Tag>}<ArrowRightOutlined style={{ color: '#94a3b8', fontSize: 12 }} /></Space>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title={<Text strong style={{ fontSize: 15 }}>快捷操作</Text>} style={{ borderRadius: 12, height: '100%' }} styles={{ body: { padding: '16px 20px' } }}>
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Button type="primary" block icon={<FileSearchOutlined />} onClick={() => navigate('/review')} style={{ borderRadius: 8, height: 40 }}>新建审查</Button>
              <Button block icon={<AuditOutlined />} onClick={() => navigate('/reports')} style={{ borderRadius: 8, height: 40 }}>查看报告</Button>
              <Button block icon={<WarningOutlined />} onClick={() => navigate('/rules')} style={{ borderRadius: 8, height: 40 }}>管理规则</Button>
              <Button block icon={<CheckCircleOutlined />} onClick={() => navigate('/manage/users')} style={{ borderRadius: 8, height: 40 }}>用户管理</Button>
            </Space>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col span={24}>
          <RecentActivity
            title="最近审查活动"
            items={(data?.recent_reports || []).slice(0, 10).map((r: any) => ({
              id: r.id,
              title: r.source_file || r.title || `审查报告 #${r.id}`,
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

export default AdminDashboard
