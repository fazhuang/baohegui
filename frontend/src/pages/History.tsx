import React, { useEffect, useState, useMemo } from 'react'
import { Table, Tag, Typography, Spin, Button, Card, Input, DatePicker, Checkbox, Space } from 'antd'
import { useNavigate } from 'react-router-dom'
import {
  ReloadOutlined, WarningOutlined,
  SearchOutlined, SwapOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { listReports } from '../services/api'
import type { ReportListItem } from '../types'

const { Title, Text } = Typography

type PageState = 'loading' | 'empty' | 'error' | 'data'

const HistoryPage: React.FC = () => {
  const navigate = useNavigate()
  const [reports, setReports] = useState<ReportListItem[]>([])
  const [state, setState] = useState<PageState>('loading')
  const [errorMsg, setErrorMsg] = useState('')

  // 搜索 / 日期 / 对比
  const [searchText, setSearchText] = useState('')
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null)
  const [compareSet, setCompareSet] = useState<Set<number>>(new Set())

  const fetchData = () => {
    setState('loading')
    listReports()
      .then((data) => {
        setReports(data)
        setState(data.length === 0 ? 'empty' : 'data')
      })
      .catch((err) => {
        const msg = err?.response?.data?.detail || err.message || '加载失败'
        setErrorMsg(msg)
        setState('error')
      })
  }

  useEffect(() => {
    fetchData()
  }, [])

  // 筛选
  const filteredReports = useMemo(() => {
    let list = reports
    if (searchText) {
      const q = searchText.toLowerCase()
      list = list.filter((r) =>
        String(r.id).includes(q) || String(r.file_id).includes(q)
      )
    }
    if (dateRange && dateRange[0] && dateRange[1]) {
      const start = dateRange[0].startOf('day')
      const end = dateRange[1].endOf('day')
      list = list.filter((r) => {
        const d = dayjs(r.created_at)
        return d.isAfter(start) && d.isBefore(end)
      })
    }
    return list
  }, [reports, searchText, dateRange])

  // 对比跳转
  const goCompare = () => {
    const ids = Array.from(compareSet)
    if (ids.length === 2) {
      // Navigate to admin panel compare tab with preselected IDs
      navigate(`/admin/panel?tab=compare&a=${ids[0]}&b=${ids[1]}`)
    }
  }

  const toggleCompare = (id: number) => {
    setCompareSet((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        if (next.size >= 2) {
          // remove oldest and add new
          const arr = Array.from(next)
          next.delete(arr[0])
        }
        next.add(id)
      }
      return next
    })
  }

  const columns = [
    { title: '报告ID', dataIndex: 'id', key: 'id', width: 80 },
    { title: '文件ID', dataIndex: 'file_id', key: 'file_id', width: 80 },
    {
      title: '合规评分', dataIndex: 'total_score', key: 'total_score', width: 120,
      render: (score: number) => (
        <Tag color={score >= 85 ? 'green' : score >= 60 ? 'gold' : 'red'}>{score}</Tag>
      ),
    },
    { title: '违规数', dataIndex: 'violation_count', key: 'violation_count', width: 80 },
    {
      title: '检查时间', dataIndex: 'created_at', key: 'created_at', width: 180,
      render: (t: string) => dayjs(t).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作', key: 'action', width: 140,
      render: (_: any, record: ReportListItem) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => navigate(`/report/${record.id}`)}>
            查看详情
          </Button>
          <Checkbox
            checked={compareSet.has(record.id)}
            onChange={() => toggleCompare(record.id)}
          />
        </Space>
      ),
    },
  ]

  // ── Loading ──────────────────────────────────────────
  if (state === 'loading') {
    return (
      <div className="state-container">
        <Spin size="large" />
        <Text type="secondary" style={{ marginTop: 16 }}>加载历史记录...</Text>
      </div>
    )
  }

  // ── Error ────────────────────────────────────────────
  if (state === 'error') {
    return (
      <div className="state-container">
        <WarningOutlined style={{ fontSize: 48, color: 'var(--color-error)' }} />
        <Title level={4} style={{ marginTop: 8 }}>加载失败</Title>
        <Text type="secondary" style={{ marginBottom: 20, display: 'block' }}>
          {errorMsg.includes('Network') || errorMsg.includes('connect')
            ? '无法连接到服务器，请确认后端服务已启动'
            : errorMsg}
        </Text>
        <Button icon={<ReloadOutlined />} onClick={fetchData}>
          重新加载
        </Button>
      </div>
    )
  }

  // ── Empty ────────────────────────────────────────────
  if (state === 'empty') {
    return (
      <div>
        <Title level={3}>历史记录</Title>
        <div className="state-container" style={{ padding: '80px 24px' }}>
          <svg className="empty-state-illustration" viewBox="0 0 120 120" fill="none">
            <rect x="25" y="20" width="70" height="80" rx="4" stroke="currentColor" strokeWidth="2" />
            <line x1="35" y1="40" x2="85" y2="40" stroke="currentColor" strokeWidth="2" />
            <line x1="35" y1="55" x2="75" y2="55" stroke="currentColor" strokeWidth="1.5" />
            <line x1="35" y1="65" x2="65" y2="65" stroke="currentColor" strokeWidth="1.5" />
            <line x1="35" y1="75" x2="80" y2="75" stroke="currentColor" strokeWidth="1.5" />
            <circle cx="95" cy="95" r="15" stroke="currentColor" strokeWidth="2" />
            <path d="M95 88 L95 95 L101 101" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <Title level={4} style={{ color: 'var(--color-text-tertiary)', marginTop: 16 }}>暂无历史记录</Title>
          <Text type="secondary" style={{ marginBottom: 20, display: 'block' }}>
            上传第一份文件开始使用
          </Text>
          <Button type="primary" onClick={() => navigate('/')}>
            上传文件
          </Button>
        </div>
      </div>
    )
  }

  // ── 评分趋势面积图 ──────────────────────────────────
  const ScoreTrend: React.FC = () => {
    if (reports.length < 2) return null
    const data = reports.slice().reverse().slice(-10)
    const w = 640, h = 180, px = 44, py = 24
    const maxScore = 100
    const xStep = (w - px - 24) / Math.max(data.length - 1, 1)
    const pts = data.map((r, i) => ({
      x: px + i * xStep,
      y: h - py - (r.total_score / maxScore) * (h - 2 * py),
      score: r.total_score,
      label: `#${r.id}`,
    }))

    const line = pts.map(p => `${p.x},${p.y}`).join(' ')
    // Area polygon: line + bottom corners
    const areaPath = `${pts[0].x},${h - py} ${line} ${pts[pts.length - 1].x},${h - py}`

    return (
      <Card size="small" style={{ marginBottom: 16, borderRadius: 8 }}>
        <Text strong style={{ fontSize: 13 }}>合规评分趋势（最近 {data.length} 次）</Text>
        <svg viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', maxHeight: h, marginTop: 8 }}>
          {/* 网格线 */}
          {[0, 25, 50, 75, 100].map(v => {
            const y = h - py - (v / maxScore) * (h - 2 * py)
            return <g key={v}>
              <line x1={px} y1={y} x2={w - 12} y2={y} stroke="var(--color-border)" strokeWidth={1} />
              <text x={px - 8} y={y + 4} textAnchor="end" fontSize={10} fill="var(--color-text-tertiary)">{v}</text>
            </g>
          })}
          {/* 面积填充 */}
          <polygon points={areaPath} fill="rgba(37,99,235,0.08)" />
          {/* 折线 */}
          <polyline points={line} fill="none" stroke="var(--color-action)" strokeWidth={2} strokeLinejoin="round" />
          {/* 数据点 */}
          {pts.map((p, i) => (
            <g key={i}>
              <circle cx={p.x} cy={p.y} r={4} fill="var(--color-action)" stroke="#fff" strokeWidth={2} />
              <text x={p.x} y={p.y - 10} textAnchor="middle" fontSize={10} fill="var(--color-text-secondary)">
                {p.score}
              </text>
            </g>
          ))}
          {/* X轴标签 */}
          {pts.map((p, i) => (
            <text key={i} x={p.x} y={h - 4} textAnchor="middle" fontSize={9} fill="var(--color-text-tertiary)">
              {p.label}
            </text>
          ))}
        </svg>
      </Card>
    )
  }

  // ── Data ─────────────────────────────────────────────
  return (
    <div>
      {/* Header */}
      <div className="admin-page-header">
        <div>
          <Title level={3} style={{ margin: 0, fontSize: 20 }}>历史记录</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>
            共 {reports.length} 份报告
          </Text>
        </div>
        <Space size={8}>
          {compareSet.size === 2 && (
            <Button type="primary" icon={<SwapOutlined />} onClick={goCompare}>
              对比选中
            </Button>
          )}
          {compareSet.size > 0 && compareSet.size < 2 && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              再选 1 项进行对比
            </Text>
          )}
        </Space>
      </div>

      {/* Score trend */}
      <ScoreTrend />

      {/* Search + Date Filter */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <Input
          placeholder="搜索报告ID / 文件ID"
          prefix={<SearchOutlined />}
          allowClear
          style={{ width: 220 }}
          size="small"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
        />
        <DatePicker.RangePicker
          size="small"
          style={{ width: 240 }}
          value={dateRange as any}
          onChange={(v) => setDateRange(v as any)}
          placeholder={['开始日期', '结束日期']}
        />
      </div>

      <Table
        dataSource={filteredReports}
        columns={columns}
        rowKey="id"
        pagination={{ pageSize: 20 }}
        rowClassName={(record) => compareSet.has(record.id) ? 'ant-table-row-selected' : ''}
      />
    </div>
  )
}

export default HistoryPage
