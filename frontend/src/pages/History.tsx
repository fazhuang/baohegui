import React, { useState, useMemo } from 'react'
import {
  Button, Card, Checkbox, Col, DatePicker, Empty, Input, Row, Select, Slider,
  Space, Spin, Table, Tag, Typography,
} from 'antd'
import type { TablePaginationConfig } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ReloadOutlined, SearchOutlined, SwapOutlined, WarningOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ReportListItem } from '../types'
import { useReportHistory, SORT_OPTIONS, DEFAULT_PAGE_SIZE } from '../features/history/hooks/useReportHistory'
import TrendChart from '../features/history/components/TrendChart'

const { Title, Text } = Typography

const HistoryPage: React.FC = () => {
  const navigate = useNavigate()
  const [compareSet, setCompareSet] = useState<Set<number>>(new Set())
  const {
    reports, total, page, pageSize, loading, errorMsg,
    searchText, dateFrom, dateTo, scoreMin, scoreMax, sortBy, sortOrder,
    trendReports, hasFilters,
    setSearchText, loadReports, resetFilters, applySort, applyScoreRange, applyDateFrom, applyDateTo, handleSearch,
  } = useReportHistory()

  const handleTableChange = (pagination: TablePaginationConfig) => {
    loadReports({ page: pagination.current || 1, page_size: pagination.pageSize || DEFAULT_PAGE_SIZE })
  }

  const toggleCompare = (id: number) => {
    setCompareSet(prev => {
      const next = new Set(prev)
      if (next.has(id)) { next.delete(id) }
      else { if (next.size >= 2) { next.delete(Array.from(next)[0]) } next.add(id) }
      return next
    })
  }

  const goCompare = () => {
    const ids = Array.from(compareSet)
    if (ids.length === 2) navigate(`/admin/panel?tab=compare&a=${ids[0]}&b=${ids[1]}`)
  }

  const columns = useMemo(() => [
    { title: '报告ID', dataIndex: 'id', key: 'id', width: 90 },
    { title: '文件ID', dataIndex: 'file_id', key: 'file_id', width: 90 },
    { title: '文件名', dataIndex: 'file_name', key: 'file_name', ellipsis: true, render: (v: string) => v || '-' },
    { title: '合规评分', dataIndex: 'total_score', key: 'total_score', width: 120,
      render: (s: number) => <Tag color={s >= 85 ? 'green' : s >= 60 ? 'gold' : 'red'}>{s}</Tag> },
    { title: '违规数', dataIndex: 'violation_count', key: 'violation_count', width: 90 },
    { title: '检查时间', dataIndex: 'created_at', key: 'created_at', width: 180,
      render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-' },
    { title: '操作', key: 'action', width: 140,
      render: (_: unknown, r: ReportListItem) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => navigate(`/report/${r.id}`)}>查看详情</Button>
          <Checkbox checked={compareSet.has(r.id)} onChange={() => toggleCompare(r.id)} />
        </Space>
      ) },
  ], [navigate, compareSet])

  // 加载态
  if (loading && reports.length === 0) {
    return <div className="state-container"><Spin size="large" /><Text type="secondary" style={{ marginTop: 16 }}>加载历史记录...</Text></div>
  }

  // 错误态
  if (errorMsg && reports.length === 0) {
    return (
      <div className="state-container">
        <WarningOutlined style={{ fontSize: 48, color: 'var(--color-error)' }} />
        <Title level={4} style={{ marginTop: 8 }}>加载失败</Title>
        <Text type="secondary" style={{ marginBottom: 20, display: 'block' }}>
          {errorMsg.includes('Network') || errorMsg.includes('connect') ? '无法连接到服务器，请确认后端服务已启动' : errorMsg}
        </Text>
        <Button icon={<ReloadOutlined />} onClick={() => loadReports()}>重新加载</Button>
      </div>
    )
  }

  return (
    <div>
      <div className="admin-page-header">
        <div>
          <Title level={3} style={{ margin: 0, fontSize: 20 }}>历史记录</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>共 {total} 份报告</Text>
        </div>
        <Space size={8}>
          {compareSet.size === 2 && <Button type="primary" icon={<SwapOutlined />} onClick={goCompare}>对比选中</Button>}
          {compareSet.size > 0 && compareSet.size < 2 && <Text type="secondary" style={{ fontSize: 12 }}>再选 1 项进行对比</Text>}
          <Button icon={<ReloadOutlined />} onClick={() => loadReports()}>刷新</Button>
        </Space>
      </div>

      {/* 筛选栏 */}
      <Card style={{ marginBottom: 16 }} bodyStyle={{ padding: 16 }}>
        <Row gutter={[12, 12]}>
          <Col xs={24} sm={12} md={8} lg={6}>
            <Input.Search placeholder="搜索文件名" prefix={<SearchOutlined />} allowClear enterButton="搜索"
              value={searchText} onChange={(e) => setSearchText(e.target.value)} onSearch={handleSearch} />
          </Col>
          <Col xs={12} sm={6} md={4} lg={3}>
            <DatePicker style={{ width: '100%' }} placeholder="开始日期"
              value={dateFrom ? dayjs(dateFrom) : null}
              onChange={(value) => applyDateFrom(value ? value.format('YYYY-MM-DD') : '')} />
          </Col>
          <Col xs={12} sm={6} md={4} lg={3}>
            <DatePicker style={{ width: '100%' }} placeholder="结束日期"
              value={dateTo ? dayjs(dateTo) : null}
              onChange={(value) => applyDateTo(value ? value.format('YYYY-MM-DD') : '')} />
          </Col>
          <Col xs={24} sm={12} md={6} lg={6}>
            <Space align="center" style={{ width: '100%' }}>
              <Text style={{ fontSize: 12, color: 'var(--color-text-secondary)', whiteSpace: 'nowrap' }}>评分区间</Text>
              <Slider range min={0} max={100} value={[scoreMin, scoreMax]}
                onAfterChange={(v) => applyScoreRange(v as [number, number])} style={{ flex: 1, margin: 0 }} />
            </Space>
          </Col>
          <Col xs={24} sm={12} md={4} lg={4}>
            <Select style={{ width: '100%' }} value={`${sortBy}:${sortOrder}`}
              options={SORT_OPTIONS} onChange={applySort} />
          </Col>
          <Col xs={24} sm={24} md={2} lg={2}>
            <Button block onClick={resetFilters}>重置</Button>
          </Col>
        </Row>
      </Card>

      {/* 趋势图 */}
      <Card size="small" style={{ marginBottom: 16, borderRadius: 8 }}>
        <Text strong style={{ fontSize: 13 }}>合规评分趋势（最近 {trendReports.length} 次）</Text>
        {trendReports.length < 2 ? <div style={{ padding: '20px 0' }}><Text type="secondary">暂无足够数据</Text></div> : <TrendChart reports={trendReports} />}
      </Card>

      {/* 错误提示 */}
      {errorMsg && reports.length > 0 && (
        <Card size="small" style={{ marginBottom: 16, borderColor: 'var(--color-error)' }}><Text type="danger">{errorMsg}</Text></Card>
      )}

      {/* 空态 */}
      {reports.length === 0 ? (
        <Card>
          <Empty description={hasFilters ? '没有匹配的历史记录' : '暂无历史记录'} image={Empty.PRESENTED_IMAGE_SIMPLE}>
            {hasFilters ? <Button onClick={resetFilters}>清空筛选条件</Button> : <Button type="primary" onClick={() => navigate('/')}>上传文件</Button>}
          </Empty>
        </Card>
      ) : (
        <Table dataSource={reports} columns={columns} rowKey="id" loading={loading}
          pagination={{ current: page, pageSize, total, showSizeChanger: true }}
          onChange={handleTableChange}
          rowClassName={(record) => (compareSet.has(record.id) ? 'ant-table-row-selected' : '')} />
      )}
    </div>
  )
}

export default HistoryPage
