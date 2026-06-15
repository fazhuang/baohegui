import React, { useEffect, useMemo, useState } from 'react'
import {
  Button,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Empty,
  Input,
  Row,
  Select,
  Slider,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { TablePaginationConfig } from 'antd'
import { useNavigate } from 'react-router-dom'
import {
  ReloadOutlined,
  SearchOutlined,
  SwapOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { listReports } from '../services/api'
import type { ReportListItem } from '../types'
import { getErrorMessage } from '../utils/error'

const { Title, Text } = Typography

type SortValue = `${string}:${'asc' | 'desc'}`

const DEFAULT_PAGE_SIZE = 20

const SORT_OPTIONS: Array<{ value: SortValue; label: string }> = [
  { value: 'created_at:desc', label: '最新优先' },
  { value: 'created_at:asc', label: '最早优先' },
  { value: 'total_score:desc', label: '评分从高到低' },
  { value: 'total_score:asc', label: '评分从低到高' },
  { value: 'violation_count:desc', label: '违规数从多到少' },
  { value: 'violation_count:asc', label: '违规数从少到多' },
  { value: 'file_name:asc', label: '文件名 A-Z' },
  { value: 'file_name:desc', label: '文件名 Z-A' },
]

const HistoryPage: React.FC = () => {
  const navigate = useNavigate()
  const [reports, setReports] = useState<ReportListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [loading, setLoading] = useState(true)
  const [errorMsg, setErrorMsg] = useState('')

  const [searchText, setSearchText] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [scoreMin, setScoreMin] = useState(0)
  const [scoreMax, setScoreMax] = useState(100)
  const [sortBy, setSortBy] = useState('created_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [compareSet, setCompareSet] = useState<Set<number>>(new Set())

  const loadReports = async (overrides?: {
    search?: string
    date_from?: string
    date_to?: string
    score_min?: number
    score_max?: number
    sort_by?: string
    sort_order?: string
    page?: number
    page_size?: number
  }) => {
    const params = {
      search: overrides?.search ?? searchText,
      date_from: overrides?.date_from ?? dateFrom,
      date_to: overrides?.date_to ?? dateTo,
      score_min: overrides?.score_min ?? scoreMin,
      score_max: overrides?.score_max ?? scoreMax,
      sort_by: overrides?.sort_by ?? sortBy,
      sort_order: overrides?.sort_order ?? sortOrder,
      page: overrides?.page ?? page,
      page_size: overrides?.page_size ?? pageSize,
    }

    setLoading(true)
    try {
      const data = await listReports(params)
      setReports(data.items)
      setTotal(data.total)
      setPage(data.page)
      setPageSize(data.page_size)
      setErrorMsg('')
    } catch (err: unknown) {
      setErrorMsg(getErrorMessage(err, '加载失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadReports()
  }, [])

  const resetFilters = () => {
    const nextSearch = ''
    const nextDateFrom = ''
    const nextDateTo = ''
    const nextScoreMin = 0
    const nextScoreMax = 100
    const nextSortBy = 'created_at'
    const nextSortOrder: 'asc' | 'desc' = 'desc'

    setSearchText(nextSearch)
    setDateFrom(nextDateFrom)
    setDateTo(nextDateTo)
    setScoreMin(nextScoreMin)
    setScoreMax(nextScoreMax)
    setSortBy(nextSortBy)
    setSortOrder(nextSortOrder)

    loadReports({
      search: nextSearch,
      date_from: nextDateFrom,
      date_to: nextDateTo,
      score_min: nextScoreMin,
      score_max: nextScoreMax,
      sort_by: nextSortBy,
      sort_order: nextSortOrder,
      page: 1,
      page_size: DEFAULT_PAGE_SIZE,
    })
  }

  const applySort = (value: SortValue) => {
    const [nextSortBy, nextSortOrder] = value.split(':') as [string, 'asc' | 'desc']
    setSortBy(nextSortBy)
    setSortOrder(nextSortOrder)
    loadReports({ sort_by: nextSortBy, sort_order: nextSortOrder, page: 1 })
  }

  const applyScoreRange = (value: number[] | null) => {
    const nextMin = value?.[0] ?? 0
    const nextMax = value?.[1] ?? 100
    setScoreMin(nextMin)
    setScoreMax(nextMax)
    loadReports({ score_min: nextMin, score_max: nextMax, page: 1 })
  }

  const applyDateFrom = (value: string) => {
    setDateFrom(value)
    loadReports({ date_from: value, page: 1 })
  }

  const applyDateTo = (value: string) => {
    setDateTo(value)
    loadReports({ date_to: value, page: 1 })
  }

  const handleSearch = (value: string) => {
    setSearchText(value)
    loadReports({ search: value, page: 1 })
  }

  const handleTableChange = (pagination: TablePaginationConfig) => {
    loadReports({
      page: pagination.current || 1,
      page_size: pagination.pageSize || DEFAULT_PAGE_SIZE,
    })
  }

  const goCompare = () => {
    const ids = Array.from(compareSet)
    if (ids.length === 2) {
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
          const arr = Array.from(next)
          next.delete(arr[0])
        }
        next.add(id)
      }
      return next
    })
  }

  const trendReports = useMemo(() => reports.slice().reverse().slice(-10), [reports])

  const columns = [
    { title: '报告ID', dataIndex: 'id', key: 'id', width: 90 },
    { title: '文件ID', dataIndex: 'file_id', key: 'file_id', width: 90 },
    {
      title: '文件名',
      dataIndex: 'file_name',
      key: 'file_name',
      ellipsis: true,
      render: (value: string) => value || '-',
    },
    {
      title: '合规评分',
      dataIndex: 'total_score',
      key: 'total_score',
      width: 120,
      render: (score: number) => (
        <Tag color={score >= 85 ? 'green' : score >= 60 ? 'gold' : 'red'}>{score}</Tag>
      ),
    },
    { title: '违规数', dataIndex: 'violation_count', key: 'violation_count', width: 90 },
    {
      title: '检查时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (value: string) => (value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      render: (_: unknown, record: ReportListItem) => (
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

  if (loading && reports.length === 0) {
    return (
      <div className="state-container">
        <Spin size="large" />
        <Text type="secondary" style={{ marginTop: 16 }}>加载历史记录...</Text>
      </div>
    )
  }

  if (errorMsg && reports.length === 0) {
    return (
      <div className="state-container">
        <WarningOutlined style={{ fontSize: 48, color: 'var(--color-error)' }} />
        <Title level={4} style={{ marginTop: 8 }}>加载失败</Title>
        <Text type="secondary" style={{ marginBottom: 20, display: 'block' }}>
          {errorMsg.includes('Network') || errorMsg.includes('connect')
            ? '无法连接到服务器，请确认后端服务已启动'
            : errorMsg}
        </Text>
        <Button icon={<ReloadOutlined />} onClick={() => loadReports()}>
          重新加载
        </Button>
      </div>
    )
  }

  const hasFilters =
    searchText ||
    dateFrom ||
    dateTo ||
    scoreMin !== 0 ||
    scoreMax !== 100 ||
    sortBy !== 'created_at' ||
    sortOrder !== 'desc'

  return (
    <div>
      <div className="admin-page-header">
        <div>
          <Title level={3} style={{ margin: 0, fontSize: 20 }}>历史记录</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>
            共 {total} 份报告
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
          <Button icon={<ReloadOutlined />} onClick={() => loadReports()}>
            刷新
          </Button>
        </Space>
      </div>

      <Card style={{ marginBottom: 16 }} bodyStyle={{ padding: 16 }}>
        <Row gutter={[12, 12]}>
          <Col xs={24} sm={12} md={8} lg={6}>
            <Input.Search
              placeholder="搜索文件名"
              prefix={<SearchOutlined />}
              allowClear
              enterButton="搜索"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onSearch={handleSearch}
            />
          </Col>
          <Col xs={12} sm={6} md={4} lg={3}>
            <DatePicker
              style={{ width: '100%' }}
              placeholder="开始日期"
              value={dateFrom ? dayjs(dateFrom) : null}
              onChange={(value) => applyDateFrom(value ? value.format('YYYY-MM-DD') : '')}
            />
          </Col>
          <Col xs={12} sm={6} md={4} lg={3}>
            <DatePicker
              style={{ width: '100%' }}
              placeholder="结束日期"
              value={dateTo ? dayjs(dateTo) : null}
              onChange={(value) => applyDateTo(value ? value.format('YYYY-MM-DD') : '')}
            />
          </Col>
          <Col xs={24} sm={12} md={6} lg={6}>
            <Space align="center" style={{ width: '100%' }}>
              <Text style={{ fontSize: 12, color: 'var(--color-text-secondary)', whiteSpace: 'nowrap' }}>
                评分区间
              </Text>
              <Slider
                range
                min={0}
                max={100}
                value={[scoreMin, scoreMax]}
                onAfterChange={(value) => applyScoreRange(value as number[])}
                style={{ flex: 1, margin: 0 }}
              />
            </Space>
          </Col>
          <Col xs={24} sm={12} md={4} lg={4}>
            <Select
              style={{ width: '100%' }}
              value={`${sortBy}:${sortOrder}` as SortValue}
              options={SORT_OPTIONS}
              onChange={applySort}
            />
          </Col>
          <Col xs={24} sm={24} md={2} lg={2}>
            <Button block onClick={resetFilters}>
              重置
            </Button>
          </Col>
        </Row>
      </Card>

      <Card size="small" style={{ marginBottom: 16, borderRadius: 8 }}>
        <Text strong style={{ fontSize: 13 }}>合规评分趋势（最近 {trendReports.length} 次）</Text>
        {trendReports.length < 2 ? (
          <div style={{ padding: '20px 0' }}>
            <Text type="secondary">暂无足够数据生成趋势图</Text>
          </div>
        ) : (
          <TrendChart reports={trendReports} />
        )}
      </Card>

      {errorMsg && reports.length > 0 && (
        <Card size="small" style={{ marginBottom: 16, borderColor: 'var(--color-error)' }}>
          <Text type="danger">{errorMsg}</Text>
        </Card>
      )}

      {reports.length === 0 ? (
        <Card>
          <Empty
            description={hasFilters ? '没有匹配的历史记录' : '暂无历史记录'}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            {hasFilters ? (
              <Button onClick={resetFilters}>清空筛选条件</Button>
            ) : (
              <Button type="primary" onClick={() => navigate('/')}>上传文件</Button>
            )}
          </Empty>
        </Card>
      ) : (
        <Table
          dataSource={reports}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
          }}
          onChange={handleTableChange}
          rowClassName={(record) => (compareSet.has(record.id) ? 'ant-table-row-selected' : '')}
        />
      )}
    </div>
  )
}

const TrendChart: React.FC<{ reports: ReportListItem[] }> = ({ reports }) => {
  const w = 640
  const h = 180
  const px = 44
  const py = 24
  const maxScore = 100
  const xStep = (w - px - 24) / Math.max(reports.length - 1, 1)
  const pts = reports.map((r, i) => ({
    x: px + i * xStep,
    y: h - py - (r.total_score / maxScore) * (h - 2 * py),
    score: r.total_score,
    label: `#${r.id}`,
  }))

  const line = pts.map((p) => `${p.x},${p.y}`).join(' ')
  const areaPath = `${pts[0].x},${h - py} ${line} ${pts[pts.length - 1].x},${h - py}`

  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', maxHeight: h, marginTop: 8 }}>
      {[0, 25, 50, 75, 100].map((value) => {
        const y = h - py - (value / maxScore) * (h - 2 * py)
        return (
          <g key={value}>
            <line x1={px} y1={y} x2={w - 12} y2={y} stroke="var(--color-border)" strokeWidth={1} />
            <text x={px - 8} y={y + 4} textAnchor="end" fontSize={10} fill="var(--color-text-tertiary)">
              {value}
            </text>
          </g>
        )
      })}
      <polygon points={areaPath} fill="rgba(37,99,235,0.08)" />
      <polyline points={line} fill="none" stroke="var(--color-action)" strokeWidth={2} strokeLinejoin="round" />
      {pts.map((point, index) => (
        <g key={index}>
          <circle cx={point.x} cy={point.y} r={4} fill="var(--color-action)" stroke="#fff" strokeWidth={2} />
          <text x={point.x} y={point.y - 10} textAnchor="middle" fontSize={10} fill="var(--color-text-secondary)">
            {point.score}
          </text>
        </g>
      ))}
      {pts.map((point, index) => (
        <text key={index} x={point.x} y={h - 4} textAnchor="middle" fontSize={9} fill="var(--color-text-tertiary)">
          {point.label}
        </text>
      ))}
    </svg>
  )
}

export default HistoryPage
