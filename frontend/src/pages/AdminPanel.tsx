/**
 * 管理后台综合页面 — 用户管理 / 审计日志 / 文件对比 / 计费面板
 */

import React, { useEffect, useState, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Card, Table, Tag, Button, Space, Typography,
  Tabs, Input, Modal, Form, Select, Switch, message,
  Popconfirm, Descriptions, Row, Col, Statistic, Progress,
  Alert, Empty, InputNumber,
} from 'antd'
import {
  UserOutlined, AuditOutlined, SwapOutlined, DollarOutlined,
  PlusOutlined, DeleteOutlined, EditOutlined, ReloadOutlined,
  CloseCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import {
  listUsers, createUser, updateUser, deleteUser,
  listAuditLogs, compareFiles, listReports,
  getBillingThreshold, setBillingThreshold, getBillingStatus,
} from '../services/api'
import type { UserInfo, AuditLogEntry, CompareResult } from '../services/api'

const { Title, Text } = Typography

// ═══════════════════════════════════════════════════════════════
// 1. 用户管理 Tab
// ═══════════════════════════════════════════════════════════════

const UserManageTab: React.FC = () => {
  const [users, setUsers] = useState<UserInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingUser, setEditingUser] = useState<UserInfo | null>(null)
  const [form] = Form.useForm()
  const [roleFilter, setRoleFilter] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setUsers(await listUsers())
    } catch { message.error('加载用户列表失败') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const filteredUsers = useMemo(() => {
    let list = users
    if (roleFilter) list = list.filter(u => u.role === roleFilter)
    if (statusFilter) list = list.filter(u => statusFilter === 'active' ? u.is_active : !u.is_active)
    return list
  }, [users, roleFilter, statusFilter])

  const handleCreate = async (values: any) => {
    try {
      await createUser(values)
      message.success('用户已创建')
      setModalOpen(false)
      form.resetFields()
      load()
    } catch (e: any) { message.error(e?.response?.data?.detail || '创建失败') }
  }

  const handleUpdate = async (values: any) => {
    if (!editingUser) return
    const payload: Record<string, any> = {}
    if (values.password) payload.password = values.password
    if (values.role) payload.role = values.role
    if (values.company !== undefined) payload.company = values.company
    if (values.email !== undefined) payload.email = values.email
    if (values.is_active !== undefined) payload.is_active = values.is_active
    try {
      await updateUser(editingUser.id, payload)
      message.success('用户已更新')
      setModalOpen(false)
      setEditingUser(null)
      form.resetFields()
      load()
    } catch (e: any) { message.error(e?.response?.data?.detail || '更新失败') }
  }

  const openCreate = () => {
    setEditingUser(null)
    form.resetFields()
    form.setFieldsValue({ role: 'user', is_active: true })
    setModalOpen(true)
  }

  const openEdit = (u: UserInfo) => {
    setEditingUser(u)
    form.setFieldsValue({
      role: u.role,
      company: u.company,
      email: u.email,
      is_active: u.is_active,
      password: undefined,
    })
    setModalOpen(true)
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <Title level={4}><UserOutlined /> 用户管理 ({filteredUsers.length}/{users.length})</Title>
        <Space size={8}>
          <Select
            allowClear
            placeholder="角色筛选"
            style={{ width: 110 }}
            size="small"
            value={roleFilter}
            onChange={(v) => setRoleFilter(v || null)}
            options={[
              { value: 'admin', label: '管理员' },
              { value: 'user', label: '普通用户' },
            ]}
          />
          <Select
            allowClear
            placeholder="状态筛选"
            style={{ width: 110 }}
            size="small"
            value={statusFilter}
            onChange={(v) => setStatusFilter(v || null)}
            options={[
              { value: 'active', label: '启用' },
              { value: 'disabled', label: '停用' },
            ]}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建用户</Button>
        </Space>
      </div>
      <Table dataSource={filteredUsers} rowKey="id" loading={loading} size="small"
        pagination={{ pageSize: 20 }}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 60 },
          { title: '用户名', dataIndex: 'username' },
          { title: '角色', dataIndex: 'role', width: 80,
            render: (v: string) => <Tag color={v === 'admin' ? 'red' : 'blue'}>{v}</Tag>,
          },
          { title: '单位', dataIndex: 'company', ellipsis: true },
          { title: '邮箱', dataIndex: 'email', ellipsis: true },
          { title: '状态', dataIndex: 'is_active', width: 70,
            render: (v: boolean) => v ? <Tag color="green">启用</Tag> : <Tag color="red">停用</Tag>,
          },
          { title: '创建时间', dataIndex: 'created_at', width: 180,
            render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
          },
          {
            title: '操作', width: 120,
            render: (_: any, r: UserInfo) => (
              <Space size={4}>
                <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
                <Popconfirm title="确定删除此用户？" onConfirm={async () => {
                  await deleteUser(r.id)
                  message.success('已删除')
                  load()
                }}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title={editingUser ? `编辑用户: ${editingUser.username}` : '新建用户'}
        open={modalOpen}
        onCancel={() => { setModalOpen(false); setEditingUser(null) }}
        onOk={() => form.submit()}
        destroyOnClose
      >
        <Form form={form} layout="vertical"
          onFinish={editingUser ? handleUpdate : handleCreate}
        >
          {!editingUser && (
            <>
              <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
                <Input placeholder="登录用户名" />
              </Form.Item>
              <Form.Item name="password" label="密码" rules={[{ required: true, min: 6, message: '密码至少 6 位' }]}>
                <Input.Password placeholder="登录密码" />
              </Form.Item>
            </>
          )}
          {editingUser && (
            <Form.Item name="password" label="新密码（留空不修改）">
              <Input.Password placeholder="留空则不修改密码" />
            </Form.Item>
          )}
          <Form.Item name="role" label="角色">
            <Select options={[
              { value: 'user', label: '普通用户' },
              { value: 'admin', label: '管理员' },
            ]} />
          </Form.Item>
          <Form.Item name="company" label="单位">
            <Input placeholder="所属单位" />
          </Form.Item>
          <Form.Item name="email" label="邮箱">
            <Input placeholder="电子邮箱" />
          </Form.Item>
          {editingUser && (
            <Form.Item name="is_active" label="启用状态" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 2. 审计日志 Tab
// ═══════════════════════════════════════════════════════════════

const AuditLogTab: React.FC = () => {
  const [logs, setLogs] = useState<AuditLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listAuditLogs({ limit: 200 })
      setLogs(res.logs)
      setTotal(res.total)
    } catch { message.error('加载审计日志失败') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const actionColor: Record<string, string> = {
    create_user: 'green', update_user: 'blue', delete_user: 'red',
    update_billing_threshold: 'orange',
    upload: 'cyan', check: 'geekblue',
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4}><AuditOutlined /> 操作审计 ({total})</Title>
        <Button icon={<ReloadOutlined />} onClick={load} size="small">刷新</Button>
      </div>
      <Table dataSource={logs} rowKey="id" loading={loading} size="small"
        pagination={{ pageSize: 30 }}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 60 },
          { title: '操作人', dataIndex: 'user_id', width: 80 },
          { title: '操作', dataIndex: 'action', width: 160,
            render: (v: string) => <Tag color={actionColor[v] || 'default'}>{v}</Tag>,
          },
          { title: '资源', dataIndex: 'resource', width: 80 },
          { title: '资源ID', dataIndex: 'resource_id', width: 80 },
          { title: '详情', dataIndex: 'detail', ellipsis: true, width: 200,
            render: (v: string) => v ? <Text code style={{ fontSize: 11 }}>{v}</Text> : '-',
          },
          { title: '操作时间', dataIndex: 'created_at', width: 180,
            render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
          },
        ]}
      />
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 3. 文件对比 Tab
// ═══════════════════════════════════════════════════════════════

const CompareTab: React.FC = () => {
  const [cmpSearchParams] = useSearchParams()
  const [reports, setReports] = useState<Array<{ id: number; file_id: number; filename?: string; total_score: number; created_at: string }>>([])
  const [selectedA, setSelectedA] = useState<number | null>(null)
  const [selectedB, setSelectedB] = useState<number | null>(null)
  const [result, setResult] = useState<CompareResult | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    listReports().then(data => {
      setReports(data as any[])
      const initialA = cmpSearchParams.get('a')
      const initialB = cmpSearchParams.get('b')
      if (initialA) setSelectedA(Number(initialA))
      if (initialB) setSelectedB(Number(initialB))
    }).catch(() => {})
  }, [cmpSearchParams])

  const handleCompare = async () => {
    if (!selectedA || !selectedB) return
    setLoading(true)
    try {
      const res = await compareFiles(selectedA, selectedB)
      setResult(res)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '对比失败')
    } finally { setLoading(false) }
  }

  const fileOptions = reports.map(r => ({
    value: r.file_id,
    label: `#${r.file_id} — 评分 ${r.total_score} (${r.created_at?.slice(0, 10) || '?'})`,
  }))

  return (
    <div>
      <Title level={4}><SwapOutlined /> 文件差异对比</Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        选择两个已检查的文件，对比其章节结构差异和合规评分变化
      </Text>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={10}>
          <Select placeholder="选择文件 A" options={fileOptions}
            value={selectedA} onChange={setSelectedA}
            style={{ width: '100%' }} showSearch
            filterOption={(input, option) => (option?.label as string || '').includes(input)}
          />
        </Col>
        <Col span={4} style={{ textAlign: 'center', paddingTop: 4 }}>
          <SwapOutlined style={{ fontSize: 20, color: '#999' }} />
        </Col>
        <Col span={10}>
          <Select placeholder="选择文件 B" options={fileOptions}
            value={selectedB} onChange={setSelectedB}
            style={{ width: '100%' }} showSearch
            filterOption={(input, option) => (option?.label as string || '').includes(input)}
          />
        </Col>
      </Row>

      <Button type="primary" icon={<SwapOutlined />} onClick={handleCompare}
        loading={loading} disabled={!selectedA || !selectedB} block
        style={{ marginBottom: 20, borderRadius: 8 }}>
        开始对比
      </Button>

      {result && (
        <>
          {/* 文件信息 */}
          <Card size="small" style={{ marginBottom: 16 }}>
            <Row gutter={16}>
              <Col span={12}>
                <Descriptions title="文件 A" size="small" column={1}>
                  <Descriptions.Item label="文件名">{result.info.file_a.filename}</Descriptions.Item>
                  <Descriptions.Item label="页数">{result.info.file_a.page_count}</Descriptions.Item>
                  <Descriptions.Item label="哈希">{result.info.file_a.file_hash?.slice(0, 16)}…</Descriptions.Item>
                </Descriptions>
              </Col>
              <Col span={12}>
                <Descriptions title="文件 B" size="small" column={1}>
                  <Descriptions.Item label="文件名">{result.info.file_b.filename}</Descriptions.Item>
                  <Descriptions.Item label="页数">{result.info.file_b.page_count}</Descriptions.Item>
                  <Descriptions.Item label="哈希">{result.info.file_b.file_hash?.slice(0, 16)}…</Descriptions.Item>
                </Descriptions>
              </Col>
            </Row>
            {result.info.is_same_file && (
              <Alert message="检测到同一文件（SHA-256 哈希一致）" type="info" showIcon
                style={{ marginTop: 12, borderRadius: 6 }} />
            )}
          </Card>

          {/* 章节差异 */}
          <Card size="small" title="章节结构差异" style={{ marginBottom: 16 }}>
            {result.section_diff.only_in_a.length === 0 && result.section_diff.only_in_b.length === 0 ? (
              <Empty description="两个文件的章节结构完全一致" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <div>
                <Descriptions size="small" column={2}>
                  <Descriptions.Item label={<span style={{ color: '#16a34a' }}>共有章节 ({result.section_diff.both.length})</span>}>
                    {result.section_diff.both.join(', ') || '无'}
                  </Descriptions.Item>
                </Descriptions>
                <Row gutter={16} style={{ marginTop: 12 }}>
                  <Col span={12}>
                    <Text type="secondary">仅在 A 中：</Text>
                    {result.section_diff.only_in_a.length > 0
                      ? result.section_diff.only_in_a.map(s => <Tag key={s} color="blue">{s}</Tag>)
                      : <Text type="secondary"> 无</Text>}
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">仅在 B 中：</Text>
                    {result.section_diff.only_in_b.length > 0
                      ? result.section_diff.only_in_b.map(s => <Tag key={s} color="orange">{s}</Tag>)
                      : <Text type="secondary"> 无</Text>}
                  </Col>
                </Row>
              </div>
            )}
          </Card>

          {/* 评分差异 */}
          {result.score_diff && (
            <Card size="small" title="合规评分变化">
              <Row gutter={[16, 12]}>
                {Object.entries(result.score_diff).map(([key, val]) => {
                  const delta = val.delta ?? 0
                  const color = delta > 0 ? '#16a34a' : delta < 0 ? '#dc2626' : '#6b7280'
                  return (
                    <Col span={12} key={key}>
                      <Statistic
                        title={key}
                        value={val.b}
                        suffix={
                          delta !== 0
                            ? <Text style={{ color, fontSize: 14 }}>({delta > 0 ? '+' : ''}{delta})</Text>
                            : undefined
                        }
                        valueStyle={{ fontSize: 20 }}
                      />
                      <Progress percent={val.b} size="small"
                        strokeColor={val.b >= 60 ? '#16a34a' : '#eab308'}
                      />
                    </Col>
                  )
                })}
              </Row>
            </Card>
          )}
        </>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 4. 计费面板 Tab
// ═══════════════════════════════════════════════════════════════

const BillingTab: React.FC = () => {
  const [status, setStatus] = useState<any>(null)
  const [threshold, setThreshold] = useState({ max_monthly_tokens: 1000000, max_monthly_cost_yuan: 100, alert_threshold_pct: 80 })
  const [editingThreshold, setEditingThreshold] = useState(false)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([getBillingStatus(), getBillingThreshold()])
      setStatus(s)
      setThreshold(t)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { load() }, [load])

  const handleSaveThreshold = async () => {
    setSaving(true)
    try {
      await setBillingThreshold(threshold)
      message.success('阈值已更新')
      setEditingThreshold(false)
      load()
    } catch { message.error('保存失败') }
    finally { setSaving(false) }
  }

  const severityColor = (s: string) => s === 'critical' ? '#dc2626' : '#eab308'

  return (
    <div>
      <Title level={4}><DollarOutlined /> 计费与用量</Title>

      {/* 告警 */}
      {status?.alerts?.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          {status.alerts.map((a: any, i: number) => (
            <Alert key={i} message={a.message} type={a.severity === 'critical' ? 'error' : 'warning'}
              showIcon icon={a.severity === 'critical' ? <CloseCircleOutlined /> : <WarningOutlined />}
              style={{ marginBottom: 8, borderRadius: 8, borderLeft: `4px solid ${severityColor(a.severity)}` }}
            />
          ))}
        </div>
      )}

      {/* 用量卡片 */}
      {status && (
        <Row gutter={16} style={{ marginBottom: 20 }}>
          <Col span={8}>
            <Card size="small">
              <Statistic title="Token 用量" value={status.tokens.used.toLocaleString()}
                suffix={<Text type="secondary">/ {status.tokens.limit.toLocaleString()}</Text>}
                valueStyle={{ color: status.tokens.pct >= 80 ? '#dc2626' : '#2563eb' }} />
              <Progress percent={status.tokens.pct} size="small" strokeLinecap="round"
                status={status.tokens.pct >= 100 ? 'exception' : 'active'}
                strokeColor={status.tokens.pct >= 80 ? 'var(--color-error)' : 'var(--color-action)'} />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Statistic title="费用 (元)" value={status.cost.used_yuan.toFixed(4)}
                suffix={<Text type="secondary">/ ¥{status.cost.limit_yuan}</Text>}
                precision={4}
                valueStyle={{ color: status.cost.pct >= 80 ? '#dc2626' : '#16a34a' }} />
              <Progress percent={status.cost.pct} size="small" strokeLinecap="round"
                status={status.cost.pct >= 100 ? 'exception' : 'active'}
                strokeColor={status.cost.pct >= 80 ? 'var(--color-error)' : 'var(--color-success)'} />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Statistic title="API 调用" value={status.calls.total}
                suffix={<Tag color={status.calls.success_rate >= 95 ? 'green' : 'gold'}>
                  {status.calls.success_rate}% 成功
                </Tag>} />
              <Text type="secondary" style={{ fontSize: 12 }}>当前计费周期: {status.current_period}</Text>
            </Card>
          </Col>
        </Row>
      )}

      {/* 阈值配置 */}
      <Card size="small" title="用量阈值配置"
        extra={!editingThreshold
          ? <Button size="small" icon={<EditOutlined />} onClick={() => setEditingThreshold(true)}>修改</Button>
          : <Space>
            <Button size="small" onClick={() => setEditingThreshold(false)}>取消</Button>
            <Button size="small" type="primary" loading={saving} onClick={handleSaveThreshold}>保存</Button>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Row gutter={16}>
          <Col span={8}>
            <Text type="secondary">月 Token 上限</Text>
            <InputNumber
              value={threshold.max_monthly_tokens}
              onChange={(v) => setThreshold(prev => ({ ...prev, max_monthly_tokens: v || 0 }))}
              disabled={!editingThreshold}
              style={{ width: '100%' }}
              formatter={(v) => `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
              parser={(v) => Number((v || '').replace(/,/g, ''))}
              addonAfter="tokens"
            />
          </Col>
          <Col span={8}>
            <Text type="secondary">月费用上限 (元)</Text>
            <InputNumber
              value={threshold.max_monthly_cost_yuan}
              onChange={(v) => setThreshold(prev => ({ ...prev, max_monthly_cost_yuan: v || 0 }))}
              disabled={!editingThreshold}
              style={{ width: '100%' }}
              min={0} step={10}
              addonAfter="¥"
            />
          </Col>
          <Col span={8}>
            <Text type="secondary">告警阈值 (%)</Text>
            <InputNumber
              value={threshold.alert_threshold_pct}
              onChange={(v) => setThreshold(prev => ({ ...prev, alert_threshold_pct: v || 0 }))}
              disabled={!editingThreshold}
              style={{ width: '100%' }}
              min={10} max={100} step={5}
              addonAfter="%"
            />
          </Col>
        </Row>
        <Alert
          message="当用量或费用达到告警阈值时，系统将在管理中心顶部显示告警通知。达到 100% 时仍可继续使用，建议提前扩容。"
          type="info" showIcon={false}
          style={{ marginTop: 12, background: '#f0f5ff', border: 'none', fontSize: 11, borderRadius: 6 }}
        />
      </Card>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 主组件
// ═══════════════════════════════════════════════════════════════

const AdminPanel: React.FC = () => {
  const [searchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') || 'users')

  return (
    <div>
      <Title level={3}>管理中心</Title>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'users',
            label: <span><UserOutlined /> 用户管理</span>,
            children: <UserManageTab />,
          },
          {
            key: 'audit',
            label: <span><AuditOutlined /> 审计日志</span>,
            children: <AuditLogTab />,
          },
          {
            key: 'compare',
            label: <span><SwapOutlined /> 文件对比</span>,
            children: <CompareTab />,
          },
          {
            key: 'billing',
            label: <span><DollarOutlined /> 计费面板</span>,
            children: <BillingTab />,
          },
        ]}
      />
    </div>
  )
}

export default AdminPanel
