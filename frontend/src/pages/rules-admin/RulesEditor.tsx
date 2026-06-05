import React, { useEffect, useState, useCallback } from 'react'
import {
  Card, Table, Tag, Button, Typography, Space, Input, Modal,
  Descriptions, Switch, message, Spin, Empty, Popconfirm, Tooltip,
} from 'antd'
import {
  SearchOutlined, ReloadOutlined, EditOutlined,
  CloseOutlined, CheckOutlined, AppstoreAddOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import {
  fetchAllRules, batchToggleRules,
  type RuleRecord, type RuleListResponse,
} from '../../services/rules-admin-api'

const { Title, Text } = Typography

// ── Colour maps ──────────────────────────────────────────────

const TYPE_COLOR: Record<string, string> = {
  chapter: 'blue',
  keyword: 'geekblue',
  forbidden: 'red',
  semantic: 'purple',
  pattern_required: 'cyan',
  required: 'green',
  conditional: 'orange',
  unknown: 'default',
}

const TYPE_LABEL: Record<string, string> = {
  chapter: '章节',
  keyword: '关键字',
  forbidden: '禁用词',
  semantic: '语义',
  pattern_required: '模式匹配',
  required: '必填',
  conditional: '条件',
  unknown: '未知',
}

const CATEGORY_COLOR: Record<string, string> = {
  base: 'blue',
  platform: 'green',
  industry: 'purple',
  custom: 'orange',
  draft: 'default',
}

const CATEGORY_LABEL: Record<string, string> = {
  base: '基础',
  platform: '平台',
  industry: '行业',
  custom: '自定义',
  draft: '草稿',
  qualification: '资格条件',
  evaluation: '评标标准',
  commercial: '商务条款',
  procedural: '程序合规',
  legal_conflict: '法规冲突',
}

// ── Main page ────────────────────────────────────────────────

const RulesEditor: React.FC = () => {
  const [rules, setRules] = useState<RuleRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [batchLoading, setBatchLoading] = useState(false)
  const [detailRule, setDetailRule] = useState<RuleRecord | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data: RuleListResponse = await fetchAllRules(search || undefined)
      setRules(data.rules || [])
    } catch (e: any) {
      message.error('加载规则列表失败')
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [search])

  useEffect(() => {
    const timer = setTimeout(load, 300)
    return () => clearTimeout(timer)
  }, [load])

  // ── Batch toggle ───────────────────────────────────────
  const handleBatchToggle = async (enabled: boolean) => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要操作的规则')
      return
    }
    setBatchLoading(true)
    try {
      const result = await batchToggleRules(selectedRowKeys as string[], enabled)
      message.success(
        enabled
          ? `已启用 ${result.toggled} 条规则`
          : `已停用 ${result.toggled} 条规则`
      )
      setSelectedRowKeys([])
      load()
    } catch (e: any) {
      message.error(`批量操作失败: ${e.message}`)
    } finally {
      setBatchLoading(false)
    }
  }

  // ── Detail view ────────────────────────────────────────
  const showDetail = (rule: RuleRecord) => {
    setDetailRule(rule)
    setDetailOpen(true)
  }

  // ── Loading ────────────────────────────────────────────
  if (loading && rules.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" tip="加载规则列表..." />
      </div>
    )
  }

  // ── Error ──────────────────────────────────────────────
  if (error && rules.length === 0) {
    return (
      <div>
        <Title level={3}>
          <AppstoreAddOutlined style={{ marginRight: 8 }} />规则编辑器
        </Title>
        <Card>
          <Empty
            description={`加载失败: ${error}`}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            <Button icon={<ReloadOutlined />} onClick={load}>重试</Button>
          </Empty>
        </Card>
      </div>
    )
  }

  const rowSelection = {
    selectedRowKeys,
    onChange: (keys: React.Key[]) => setSelectedRowKeys(keys),
  }

  return (
    <div>
      {/* ── Header ── */}
      <div style={{ marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            <AppstoreAddOutlined style={{ marginRight: 8 }} />规则编辑器
          </Title>
          <Text type="secondary">查看、搜索和批量管理规则</Text>
        </div>
        <Space wrap>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
            刷新
          </Button>
        </Space>
      </div>

      {/* ── Toolbar ── */}
      <Card size="small" style={{ marginBottom: 16, borderRadius: 10 }}>
        <Space wrap size="middle">
          <Input
            prefix={<SearchOutlined />}
            placeholder="搜索规则 ID / 描述 / 平台..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: 280 }}
            allowClear
          />
          <Popconfirm
            title={`确认${selectedRowKeys.length} 条规则？`}
            icon={<ExclamationCircleOutlined style={{ color: '#16a34a' }} />}
            onConfirm={() => handleBatchToggle(true)}
            okText="确认启用"
            cancelText="取消"
          >
            <Button
              icon={<CheckOutlined />}
              type="primary"
              disabled={selectedRowKeys.length === 0}
              loading={batchLoading}
            >
              批量启用 ({selectedRowKeys.length})
            </Button>
          </Popconfirm>
          <Popconfirm
            title={`确认停用${selectedRowKeys.length} 条规则？`}
            icon={<ExclamationCircleOutlined style={{ color: '#dc2626' }} />}
            onConfirm={() => handleBatchToggle(false)}
            okText="确认停用"
            okButtonProps={{ danger: true }}
            cancelText="取消"
          >
            <Button
              icon={<CloseOutlined />}
              danger
              disabled={selectedRowKeys.length === 0}
              loading={batchLoading}
            >
              批量停用 ({selectedRowKeys.length})
            </Button>
          </Popconfirm>
          {selectedRowKeys.length > 0 && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              已选择 {selectedRowKeys.length} 条规则
            </Text>
          )}
        </Space>
      </Card>

      {/* ── Rules table ── */}
      <Card style={{ borderRadius: 10 }}>
        {rules.length === 0 ? (
          <Empty
            description={search ? `未找到匹配 "${search}" 的规则` : '暂无规则'}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            {search && (
              <Button onClick={() => setSearch('')}>清除搜索</Button>
            )}
          </Empty>
        ) : (
          <Table
            rowSelection={rowSelection}
            dataSource={rules}
            rowKey="rule_id"
            size="middle"
            loading={loading}
            pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (total) => `共 ${total} 条规则` }}
            columns={[
              {
                title: '规则 ID',
                dataIndex: 'rule_id',
                key: 'rule_id',
                width: 140,
                ellipsis: true,
                render: (v: string, r: RuleRecord) => (
                  <Button type="link" size="small" onClick={() => showDetail(r)} style={{ padding: 0 }}>
                    <Text code style={{ fontSize: 12 }}>{v}</Text>
                  </Button>
                ),
              },
              {
                title: '类型',
                dataIndex: 'rule_type',
                key: 'rule_type',
                width: 90,
                render: (v: string) => (
                  <Tag color={TYPE_COLOR[v] || 'default'}>{TYPE_LABEL[v] || v}</Tag>
                ),
              },
              {
                title: '目标字段',
                dataIndex: 'target',
                key: 'target',
                width: 120,
                ellipsis: true,
                render: (v: string) => v || '-',
              },
              {
                title: '描述',
                dataIndex: 'description',
                key: 'description',
                ellipsis: true,
              },
              {
                title: '分类',
                dataIndex: 'category',
                key: 'category',
                width: 90,
                render: (v: string) => (
                  <Tag color={CATEGORY_COLOR[v] || 'default'}>
                    {CATEGORY_LABEL[v] || v}
                  </Tag>
                ),
              },
              {
                title: '版本',
                dataIndex: 'version',
                key: 'version',
                width: 70,
              },
              {
                title: '启用',
                dataIndex: 'enabled',
                key: 'enabled',
                width: 70,
                render: (v: boolean) => (
                  <Tag color={v ? 'green' : 'red'}>{v ? '是' : '否'}</Tag>
                ),
              },
              {
                title: '操作',
                key: 'action',
                width: 80,
                render: (_: any, r: RuleRecord) => (
                  <Tooltip title="查看详情">
                    <Button
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => showDetail(r)}
                    />
                  </Tooltip>
                ),
              },
            ]}
          />
        )}
      </Card>

      {/* ── Detail modal ── */}
      <Modal
        title={
          <Space>
            <EditOutlined />
            <span>规则详情</span>
            {detailRule && <Tag color="blue">{detailRule.rule_id}</Tag>}
          </Space>
        }
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={[
          <Button key="close" onClick={() => setDetailOpen(false)}>
            关闭
          </Button>,
        ]}
        width={640}
      >
        {detailRule && (
          <Descriptions column={1} bordered size="small" style={{ marginTop: 8 }}>
            <Descriptions.Item label="规则 ID">
              <Text code>{detailRule.rule_id}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="平台">
              {detailRule.platform || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="平台代码">
              {detailRule.platform_code || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="类型">
              <Tag color={TYPE_COLOR[detailRule.rule_type] || 'default'}>
                {TYPE_LABEL[detailRule.rule_type] || detailRule.rule_type}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="目标字段">
              {detailRule.target || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="强制">
              <Tag color={detailRule.mandatory ? 'red' : 'green'}>
                {detailRule.mandatory ? '是' : '否'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="描述" span={2}>
              {detailRule.description || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="分类">
              <Tag color={CATEGORY_COLOR[detailRule.category] || 'default'}>
                {CATEGORY_LABEL[detailRule.category] || detailRule.category}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="版本">
              {detailRule.version || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="生效日期">
              {detailRule.effective_date
                ? new Date(detailRule.effective_date).toLocaleDateString('zh-CN')
                : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="启用状态">
              <Switch
                checked={detailRule.enabled}
                disabled
                checkedChildren="启用"
                unCheckedChildren="停用"
              />
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  )
}

export default RulesEditor
