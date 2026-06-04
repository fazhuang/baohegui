import React, { useEffect, useState, useCallback } from 'react'
import {
  Card, Table, Tag, Button, Space, Typography, Spin,
  Tabs, Input, Select, Modal, Form, Switch, message,
  Popconfirm, Tooltip, Empty, Row, Col, Statistic, Descriptions, Progress,
} from 'antd'
import {
  ReloadOutlined, PlusOutlined, DeleteOutlined, EditOutlined,
  SyncOutlined, WarningOutlined, CheckCircleOutlined,
  CloseCircleOutlined, SearchOutlined, FileAddOutlined,
  DashboardOutlined, SettingOutlined,
} from '@ant-design/icons'
import {
  listPlatformRules, togglePlatformRule,
  deletePlatformRule, updatePlatformRule, createPlatformRule,
  reloadRules, runSync, getSyncStatus, getSyncHistory,
  getDashboardStats,
} from '../services/api'
import type {
  PlatformRule, SyncHistoryItem, SyncStatus, DashboardStats,
} from '../types'

const { Title, Text } = Typography

// ── 颜色映射 ────────────────────────────────────────────────
const typeColor: Record<string, string> = {
  chapter: 'blue', keyword: 'geekblue', forbidden: 'red',
  semantic: 'purple', unknown: 'default',
}
const typeLabel: Record<string, string> = {
  chapter: '章节', keyword: '关键字', forbidden: '禁用词',
  semantic: '语义', unknown: '未知',
}
const categoryLabel: Record<string, string> = {
  base: '基础', platform: '平台', industry: '行业',
  custom: '自定义', draft: '草稿',
}

// ═══════════════════════════════════════════════════════════════
// Tab 1: 规则列表
// ═══════════════════════════════════════════════════════════════

const RuleListTab: React.FC = () => {
  const [rules, setRules] = useState<PlatformRule[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<string | null>(null)
  const [editRule, setEditRule] = useState<PlatformRule | null>(null)
  const [editOpen, setEditOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)

  const fetch = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listPlatformRules({ search: search || undefined })
      setRules(data.rules)
    } catch { message.error('加载规则失败') }
    setLoading(false)
  }, [search])

  useEffect(() => { fetch() }, [fetch])

  const handleToggle = async (id: string) => {
    const enabled = await togglePlatformRule(id)
    message.success(`规则已${enabled ? '启用' : '停用'}`)
    fetch()
  }

  const handleDelete = async (id: string) => {
    await deletePlatformRule(id)
    message.success('规则已删除')
    fetch()
  }

  const handleEdit = async (values: any) => {
    if (!editRule) return
    await updatePlatformRule(editRule.rule_id, values)
    message.success('规则已更新')
    setEditOpen(false)
    fetch()
  }

  const filtered = rules.filter(r =>
    !typeFilter || r.rule_type === typeFilter
  )

  return (
    <div>
      <Space style={{ marginBottom: 16, flexWrap: 'wrap' }}>
        <Input prefix={<SearchOutlined />} placeholder="搜索规则 ID/描述..."
          value={search} onChange={e => setSearch(e.target.value)}
          style={{ width: 240 }} allowClear />
        <Select placeholder="类型筛选" allowClear style={{ width: 120 }}
          options={[
            { value: 'chapter', label: '章节' },
            { value: 'keyword', label: '关键字' },
            { value: 'forbidden', label: '禁用词' },
            { value: 'semantic', label: '语义' },
          ]} onChange={v => setTypeFilter(v || null)} />
        <Button icon={<PlusOutlined />} type="primary"
          onClick={() => setCreateOpen(true)}>新建规则</Button>
        <Button icon={<ReloadOutlined />} onClick={() => { reloadRules(); fetch() }}>
          热加载
        </Button>
      </Space>

      <Table dataSource={filtered} rowKey="rule_id" loading={loading}
        size="small" pagination={{ pageSize: 20 }}
        columns={[
          { title: '规则 ID', dataIndex: 'rule_id', key: 'rule_id', width: 130 },
          { title: '类型', dataIndex: 'rule_type', key: 'rule_type', width: 80,
            render: (v: string) => <Tag color={typeColor[v]}>{typeLabel[v]}</Tag> },
          { title: '目标', dataIndex: 'target', key: 'target', width: 120 },
          { title: '描述', dataIndex: 'description', key: 'description' },
          { title: '分类', dataIndex: 'category', key: 'category', width: 80,
            render: (v: string) => <Tag>{categoryLabel[v] || v}</Tag> },
          { title: '版本', dataIndex: 'version', key: 'version', width: 60 },
          { title: '启用', dataIndex: 'enabled', key: 'enabled', width: 60,
            render: (v: boolean, r: PlatformRule) =>
              <Switch size="small" checked={v}
                onChange={() => handleToggle(r.rule_id)} /> },
          { title: '操作', key: 'action', width: 120,
            render: (_: any, r: PlatformRule) => (
              <Space>
                <Button size="small" icon={<EditOutlined />}
                  onClick={() => { setEditRule(r); setEditOpen(true) }} />
                <Popconfirm title="确认删除？" onConfirm={() => handleDelete(r.rule_id)}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ) },
        ]} />

      {/* 编辑弹窗 */}
      <Modal title="编辑规则" open={editOpen} onCancel={() => setEditOpen(false)}
        footer={null} width={560}>
        {editRule && (
          <Form layout="vertical" initialValues={editRule} onFinish={handleEdit}>
            <Form.Item label="规则 ID"><Text code>{editRule.rule_id}</Text></Form.Item>
            <Form.Item label="描述" name="description">
              <Input.TextArea rows={2} />
            </Form.Item>
            <Form.Item label="类型" name="rule_type">
              <Select options={[
                { value: 'chapter', label: '章节' },
                { value: 'keyword', label: '关键字' },
                { value: 'forbidden', label: '禁用词' },
                { value: 'semantic', label: '语义' },
              ]} />
            </Form.Item>
            <Form.Item label="目标" name="target"><Input /></Form.Item>
            <Form.Item label="分类" name="category">
              <Select options={[
                { value: 'base', label: '基础' },
                { value: 'platform', label: '平台' },
                { value: 'draft', label: '草稿' },
              ]} />
            </Form.Item>
            <Form.Item label="版本号" name="version"><Input /></Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit">保存</Button>
            </Form.Item>
          </Form>
        )}
      </Modal>

      {/* 新建弹窗 */}
      <Modal title="新建规则" open={createOpen} onCancel={() => setCreateOpen(false)}
        footer={null} width={560}>
        <Form layout="vertical" onFinish={async (v) => {
          await createPlatformRule(v)
          message.success('规则已创建')
          setCreateOpen(false)
          fetch()
        }}>
          <Form.Item label="规则 ID" name="rule_id" rules={[{ required: true }]}>
            <Input placeholder="如: CUSTOM-001" />
          </Form.Item>
          <Form.Item label="平台" name="platform" initialValue="自定义">
            <Input />
          </Form.Item>
          <Form.Item label="平台代码" name="platform_code">
            <Input placeholder="如: CUS-001" />
          </Form.Item>
          <Form.Item label="类型" name="rule_type" initialValue="forbidden">
            <Select options={[
              { value: 'chapter', label: '章节' },
              { value: 'keyword', label: '关键字' },
              { value: 'forbidden', label: '禁用词' },
            ]} />
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item label="目标" name="target"><Input /></Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">创建</Button>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Tab 2: 同步管理
// ═══════════════════════════════════════════════════════════════

const SyncTab: React.FC = () => {
  const [status, setStatus] = useState<SyncStatus | null>(null)
  const [history, setHistory] = useState<SyncHistoryItem[]>([])
  const [syncing, setSyncing] = useState(false)

  const fetch = useCallback(async () => {
    try {
      setStatus(await getSyncStatus())
      setHistory(await getSyncHistory())
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { fetch() }, [fetch])

  const handleSync = async (platform: string) => {
    setSyncing(true)
    try {
      const result = await runSync(platform)
      message.success(`同步完成：新增${result.new_rules} 更新${result.updated_rules}`)
      fetch()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '同步失败')
    }
    setSyncing(false)
  }

  const statusColor = (s: string) =>
    s === 'success' ? 'green' : s === 'failed' ? 'red' : s === 'running' ? 'blue' : 'default'

  return (
    <div>
      <Card title="同步状态" style={{ marginBottom: 16 }}>
        {status && (
          <Space direction="vertical" size={8}>
            <Text>引擎规则: <strong>{status.rule_engine_loaded}</strong> 条</Text>
            <Text>平台规则: <strong>{status.total_rules}</strong> 条 (启用 {status.enabled_rules})</Text>
            <Text>可用平台: {status.available_platforms?.join('、')}</Text>
            {status.last_sync && (
              <Text type="secondary">
                上次同步: {status.last_sync.platform} · {status.last_sync.time} · {status.last_sync.status}
              </Text>
            )}
          </Space>
        )}
      </Card>

      <Card title="立即同步" style={{ marginBottom: 16 }}>
        <Space wrap>
          {(status?.available_platforms || ['广东省公共资源交易平台']).map(p => (
            <Button key={p} icon={<SyncOutlined />} loading={syncing}
              onClick={() => handleSync(p)} disabled={syncing}>
              同步 {p}
            </Button>
          ))}
        </Space>
      </Card>

      <Card title="同步历史">
        <Table dataSource={history} rowKey="id" size="small"
          pagination={{ pageSize: 10 }}
          columns={[
            { title: '平台', dataIndex: 'platform', key: 'platform', width: 160 },
            { title: '状态', dataIndex: 'status', key: 'status', width: 80,
              render: (v: string) => <Tag color={statusColor(v)}>{v}</Tag> },
            { title: '新增', dataIndex: 'new_rules', key: 'new_rules', width: 60 },
            { title: '更新', dataIndex: 'updated_rules', key: 'updated_rules', width: 60 },
            { title: '重试', dataIndex: 'retry_count', key: 'retry_count', width: 60 },
            { title: '版本', dataIndex: 'version', key: 'version', width: 80 },
            { title: '时间', dataIndex: 'finished_at', key: 'finished_at', width: 160 },
            { title: '错误', dataIndex: 'errors', key: 'errors',
              render: (e: string[]) => e?.length
                ? <Tooltip title={e.join('; ')}><Tag color="red">{e.length} 个</Tag></Tooltip>
                : '-' },
          ]} />
      </Card>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Tab 3: 拦截反馈管理
// ═══════════════════════════════════════════════════════════════

const FeedbackTab: React.FC = () => {
  const [drafts, setDrafts] = useState<PlatformRule[]>([])
  const [loading, setLoading] = useState(true)

  const fetch = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listPlatformRules({ search: 'draft' })
      setDrafts(data.rules.filter(r => r.category === 'draft'))
    } catch { /* ignore */ }
    setLoading(false)
  }, [])

  useEffect(() => { fetch() }, [fetch])

  const handleActivate = async (r: PlatformRule) => {
    await updatePlatformRule(r.rule_id, { enabled: true, category: 'custom' })
    message.success('规则已启用')
    fetch()
  }

  const handleIgnore = async (r: PlatformRule) => {
    await deletePlatformRule(r.rule_id)
    message.success('已忽略')
    fetch()
  }

  if (loading) return <Spin style={{ display: 'block', textAlign: 'center', padding: 40 }} />

  return (
    <div>
      {drafts.length === 0 ? (
        <Empty description="暂无拦截反馈" />
      ) : (
        <Table dataSource={drafts} rowKey="rule_id" size="small"
          columns={[
            { title: '规则 ID', dataIndex: 'rule_id', key: 'rule_id', width: 150 },
            { title: '平台', dataIndex: 'platform', key: 'platform', width: 160 },
            { title: '代码', dataIndex: 'platform_code', key: 'platform_code', width: 100 },
            { title: '描述', dataIndex: 'description', key: 'description' },
            { title: '提交时间', dataIndex: 'effective_date', key: 'date', width: 120 },
            { title: '操作', key: 'action', width: 180,
              render: (_: any, r: PlatformRule) => (
                <Space>
                  <Button size="small" type="primary" icon={<CheckCircleOutlined />}
                    onClick={() => handleActivate(r)}>转为规则</Button>
                  <Button size="small" danger icon={<CloseCircleOutlined />}
                    onClick={() => handleIgnore(r)}>忽略</Button>
                </Space>
              ) },
          ]} />
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Tab 4: 系统看板
// ═══════════════════════════════════════════════════════════════

const DashboardTab: React.FC = () => {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(true)

  const fetch = useCallback(async () => {
    setLoading(true)
    try { setStats(await getDashboardStats()) }
    catch { message.error('加载统计数据失败') }
    setLoading(false)
  }, [])

  useEffect(() => { fetch() }, [fetch])

  if (loading) return <Spin style={{ display: 'block', textAlign: 'center', padding: 40 }} />

  if (!stats) return <Empty description="无法加载统计数据" />

  const { rules, llm, risk_distribution, industries } = stats
  const totalByType = Object.values(rules.by_type).reduce((a, b) => a + b, 0)

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="规则总数" value={totalByType} suffix="条" /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="LLM 调用" value={llm.total_calls} suffix="次" /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="Token 消耗" value={llm.total_tokens} suffix="" /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card><Statistic title="成功率" value={llm.success_rate} suffix="%" precision={1} /></Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} sm={12}>
          <Card title="规则类型分布" size="small">
            <Descriptions column={1} size="small">
              <Descriptions.Item label="章节完整性">
                <Progress percent={Math.round(rules.chapter_required / totalByType * 100)} size="small" />
                <Text style={{ marginLeft: 8 }}>{rules.chapter_required} 条</Text>
              </Descriptions.Item>
              <Descriptions.Item label="关键字合规">
                <Progress percent={Math.round(rules.keyword_required / totalByType * 100)} size="small" />
                <Text style={{ marginLeft: 8 }}>{rules.keyword_required} 条</Text>
              </Descriptions.Item>
              <Descriptions.Item label="禁用词">
                <Progress percent={Math.round(rules.forbidden / totalByType * 100)} size="small" />
                <Text style={{ marginLeft: 8 }}>{rules.forbidden} 条</Text>
              </Descriptions.Item>
              <Descriptions.Item label="格式要求">
                <Progress percent={Math.round(rules.format_required / totalByType * 100)} size="small" />
                <Text style={{ marginLeft: 8 }}>{rules.format_required} 条</Text>
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col xs={24} sm={12}>
          <Card title="风险等级分布" size="small">
            <Descriptions column={1} size="small">
              <Descriptions.Item label="高风险">
                <Progress percent={Math.round(risk_distribution.high / totalByType * 100)} strokeColor="#dc2626" size="small" />
                <Text style={{ marginLeft: 8 }}>{risk_distribution.high} 条</Text>
              </Descriptions.Item>
              <Descriptions.Item label="中风险">
                <Progress percent={Math.round(risk_distribution.medium / totalByType * 100)} strokeColor="#eab308" size="small" />
                <Text style={{ marginLeft: 8 }}>{risk_distribution.medium} 条</Text>
              </Descriptions.Item>
              <Descriptions.Item label="低风险">
                <Progress percent={Math.round(risk_distribution.low / totalByType * 100)} strokeColor="#16a34a" size="small" />
                <Text style={{ marginLeft: 8 }}>{risk_distribution.low} 条</Text>
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} sm={12}>
          <Card title="可用行业" size="small">
            {industries.length > 0
              ? industries.map(ind => <Tag key={ind} style={{ marginBottom: 4 }}>{ind}</Tag>)
              : <Text type="secondary">无</Text>}
          </Card>
        </Col>
        <Col xs={24} sm={12}>
          <Card title="最近 LLM 调用" size="small">
            {llm.recent_calls.length > 0 ? (
              <div>
                {llm.recent_calls.slice(0, 5).map((c, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #f0f0f0' }}>
                    <span><Tag color={c.success ? 'green' : 'red'}>{c.model}</Tag></span>
                    <Text type="secondary" style={{ fontSize: 12 }}>{c.tokens}t · {c.duration}s</Text>
                  </div>
                ))}
              </div>
            ) : <Text type="secondary">暂无调用记录</Text>}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 主页面
// ═══════════════════════════════════════════════════════════════

const AdminRulesPage: React.FC = () => {
  return (
    <div>
      <Title level={3} style={{ marginBottom: 16 }}>
        <SettingOutlined style={{ marginRight: 8 }} />规则管理后台
      </Title>

      <Tabs
        defaultActiveKey="rules"
        items={[
          { key: 'rules', label: <span><FileAddOutlined /> 规则列表</span>,
            children: <RuleListTab /> },
          { key: 'sync', label: <span><SyncOutlined /> 同步管理</span>,
            children: <SyncTab /> },
          { key: 'feedback', label: <span><WarningOutlined /> 拦截反馈</span>,
            children: <FeedbackTab /> },
          { key: 'dashboard', label: <span><DashboardOutlined /> 系统看板</span>,
            children: <DashboardTab /> },
        ]}
      />
    </div>
  )
}

export default AdminRulesPage
