import React, { useEffect, useState, useCallback } from 'react'
import {
  Card, Table, Tag, Typography, Button, Modal, Spin, Empty, message, Tooltip,
} from 'antd'
import {
  RollbackOutlined, ExclamationCircleOutlined, FileTextOutlined,
  ReloadOutlined, HistoryOutlined,
} from '@ant-design/icons'
import {
  fetchVersions, rollbackVersion,
  type RuleVersion,
} from '../../services/rules-admin-api'

const { Title, Text, Paragraph } = Typography
const { confirm } = Modal

const RulesVersion: React.FC = () => {
  const [versions, setVersions] = useState<RuleVersion[]>([])
  const [loading, setLoading] = useState(true)
  const [rollbacking, setRollbacking] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchVersions()
      setVersions(data.versions || [])
    } catch (e: any) {
      message.error('加载版本历史失败')
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // ── Rollback handler ───────────────────────────────────
  const handleRollback = (record: RuleVersion) => {
    confirm({
      title: '确认版本回滚',
      icon: <ExclamationCircleOutlined />,
      content: (
        <div>
          <Paragraph>
            即将回滚到版本 <Tag color="blue">{record.version}</Tag>
          </Paragraph>
          <Paragraph type="secondary" style={{ fontSize: 13 }}>
            描述: {record.description || '无描述'}
          </Paragraph>
          <Paragraph type="secondary" style={{ fontSize: 13 }}>
            规则数量: {record.rule_count} · 创建时间: {new Date(record.created_at).toLocaleString('zh-CN')}
          </Paragraph>
          <Paragraph style={{ color: '#dc2626', fontSize: 13, marginTop: 8 }}>
            注意：回滚操作会替换当前所有规则，请确认后再操作。
          </Paragraph>
        </div>
      ),
      okText: '确认回滚',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setRollbacking(record.filename)
        try {
          const result = await rollbackVersion(record.filename)
          message.success(result.message || '版本回滚成功')
          load() // reload list
        } catch (e: any) {
          message.error(`回滚失败: ${e.message}`)
        } finally {
          setRollbacking(null)
        }
      },
    })
  }

  // ── Loading ────────────────────────────────────────────
  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" tip="加载版本历史..." />
      </div>
    )
  }

  // ── Error ──────────────────────────────────────────────
  if (error) {
    return (
      <div>
        <Title level={3}>
          <HistoryOutlined style={{ marginRight: 8 }} />版本历史
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

  // ── Empty ──────────────────────────────────────────────
  if (versions.length === 0) {
    return (
      <div>
        <Title level={3}>
          <HistoryOutlined style={{ marginRight: 8 }} />版本历史
        </Title>
        <Card>
          <Empty
            description="暂无版本记录"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          </Empty>
        </Card>
      </div>
    )
  }

  return (
    <div>
      <div style={{ marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            <HistoryOutlined style={{ marginRight: 8 }} />版本历史
          </Title>
          <Text type="secondary">规则版本管理与回滚</Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
          刷新
        </Button>
      </div>

      <Card style={{ borderRadius: 10 }}>
        <Table
          dataSource={versions}
          rowKey="version"
          size="middle"
          pagination={{ pageSize: 15, showSizeChanger: false }}
          columns={[
            {
              title: '版本',
              dataIndex: 'version',
              key: 'version',
              width: 140,
              render: (v: string) => (
                <Tag color="blue" style={{ fontWeight: 600, fontFamily: 'monospace' }}>
                  {v}
                </Tag>
              ),
            },
            {
              title: '描述',
              dataIndex: 'description',
              key: 'description',
              ellipsis: true,
              render: (v: string) => v || <Text type="secondary">无描述</Text>,
            },
            {
              title: '规则数量',
              dataIndex: 'rule_count',
              key: 'rule_count',
              width: 100,
              render: (v: number) => (
                <Tag icon={<FileTextOutlined />} color="green">
                  {v} 条
                </Tag>
              ),
            },
            {
              title: '创建时间',
              dataIndex: 'created_at',
              key: 'created_at',
              width: 180,
              sorter: (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
              defaultSortOrder: 'descend',
              render: (v: string) =>
                v ? new Date(v).toLocaleString('zh-CN') : '-',
            },
            {
              title: '操作',
              key: 'action',
              width: 120,
              render: (_: any, record: RuleVersion) => (
                <Tooltip title={`回滚到版本 ${record.version}`}>
                  <Button
                    size="small"
                    danger
                    icon={<RollbackOutlined />}
                    loading={rollbacking === record.filename}
                    onClick={() => handleRollback(record)}
                  >
                    回滚
                  </Button>
                </Tooltip>
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}

export default RulesVersion
