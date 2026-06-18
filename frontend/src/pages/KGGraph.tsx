/**
 * KGGraph — 知识图谱概览页
 *
 * 路由: /kg
 * 功能: 搜索、节点类型/可信度/审核状态筛选、结果列表、关联节点查看、基础统计
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  Input, Select, Slider, Row, Col, Card, List, Tag, Statistic,
  Alert, Drawer, Button, Space, Typography, Tooltip, Spin, Empty, message, Pagination,
} from 'antd';
import {
  SearchOutlined, NodeIndexOutlined, FolderOpenOutlined,
  ReadOutlined, FileTextOutlined, ApartmentOutlined,
  ReloadOutlined, SettingOutlined, SafetyCertificateOutlined,
} from '@ant-design/icons';
import { useAuthStore } from '../stores/authStore';
import { getErrorMessage } from '../utils/error';
import {
  searchKG, getRelatedNodes, getKGStats,
  seedKG, getNodesNeedingReview,
  type KGNode, type KGRelatedNode, type KGStats,
} from '../services/api';

const { Text, Paragraph } = Typography;

const NODE_TYPE_OPTIONS = [
  { label: '全部', value: '' },
  { label: '法规', value: 'regulation' },
  { label: '案例', value: 'case' },
  { label: '规则', value: 'rule' },
  { label: '模板', value: 'template' },
  { label: '概念', value: 'concept' },
];

const AUDIT_STATUS_OPTIONS = [
  { label: '全部(非已拒绝)', value: '' },
  { label: '已审核', value: 'verified' },
  { label: '未审核', value: 'unreviewed' },
  { label: '已标记', value: 'flagged' },
];

const NODE_TYPE_COLORS: Record<string, string> = {
  regulation: 'blue',
  case: 'orange',
  rule: 'green',
  template: 'purple',
  concept: 'cyan',
};

const NODE_TYPE_ICONS: Record<string, React.ReactNode> = {
  regulation: <ReadOutlined />,
  case: <FolderOpenOutlined />,
  rule: <SettingOutlined />,
  template: <FileTextOutlined />,
  concept: <ApartmentOutlined />,
};

const KGGraph: React.FC = () => {
  const isAdmin = useAuthStore(s => s.isAdmin());

  // Filters
  const [query, setQuery] = useState('');
  const [nodeType, setNodeType] = useState('');
  const [minTrust, setMinTrust] = useState(0);
  const [auditStatus, setAuditStatus] = useState('');

  // Data
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<KGNode[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<KGStats | null>(null);

  // Pagination
  const pageSize = 50;
  const [page, setPage] = useState(1);

  // Drawer
  const [selectedNode, setSelectedNode] = useState<KGNode | null>(null);
  const [relatedNodes, setRelatedNodes] = useState<KGRelatedNode[]>([]);
  const [relatedLoading, setRelatedLoading] = useState(false);

  // Admin
  const [seeding, setSeeding] = useState(false);
  const [seedError, setSeedError] = useState('');
  const [needingReviewCount, setNeedingReviewCount] = useState(0);

  // ── Search ──
  const doSearch = useCallback(async (searchPage: number = 1) => {
    setLoading(true);
    try {
      const offset = (searchPage - 1) * pageSize;
      const res = await searchKG({
        q: query || '',
        node_type: nodeType || undefined,
        min_trust: minTrust > 0 ? minTrust : undefined,
        audit_status: auditStatus || undefined,
        limit: pageSize,
        offset,
      });
      setResults(res.results);
      setTotal(res.total);
      setPage(searchPage);
    } catch {
      // handled by interceptor
    } finally {
      setLoading(false);
    }
  }, [query, nodeType, minTrust, auditStatus]);

  // Search with filter reset to page 1
  const handleSearch = useCallback(() => {
    doSearch(1);
  }, [doSearch]);

  // ── Stats ──
  const loadStats = useCallback(async () => {
    try {
      const s = await getKGStats();
      setStats(s);
    } catch {
      // ignore
    }
  }, []);

  // ── Load on mount ──
  useEffect(() => {
    handleSearch();
    loadStats();
    if (isAdmin) {
      getNodesNeedingReview().then(r => setNeedingReviewCount(r.nodes.length)).catch(() => {});
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Node click → drawer ──
  const openNodeDetail = useCallback(async (node: KGNode) => {
    setSelectedNode(node);
    setRelatedLoading(true);
    try {
      const rel = await getRelatedNodes(node.id);
      setRelatedNodes(rel.related);
    } catch {
      setRelatedNodes([]);
    } finally {
      setRelatedLoading(false);
    }
  }, []);

  // ── Admin: seed ──
  const handleSeed = useCallback(async () => {
    if (!isAdmin) return;
    setSeeding(true);
    setSeedError('');
    try {
      const res = await seedKG();
      message.success(`知识库种子完成: ${res.count} 条记录`);
      handleSearch();
      loadStats();
    } catch (error: unknown) {
      const detail = getErrorMessage(error, '初始化失败，请检查后端服务');
      setSeedError(detail);
      message.error(`知识库初始化失败：${detail}`);
    } finally {
      setSeeding(false);
    }
  }, [isAdmin, handleSearch, loadStats]);

  // ── Tag color ──
  const tagColors = (tags: string) => {
    return (tags || '').split(',').filter(Boolean).map((t, i) => (
      <Tag key={i} color="default" style={{ marginBottom: 2 }}>{t.trim()}</Tag>
    ));
  };

  return (
    <div>
      {/* ── Stats Bar ── */}
      {stats && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic title="节点总数" value={stats.total_nodes} prefix={<NodeIndexOutlined />} />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic title="法规" value={stats.by_type?.regulation ?? 0} prefix={<ReadOutlined />} valueStyle={{ color: '#1677ff' }} />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic title="案例" value={stats.by_type?.case ?? 0} prefix={<FolderOpenOutlined />} valueStyle={{ color: '#fa8c16' }} />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small">
              <Statistic title="关联边" value={stats.total_edges} prefix={<ApartmentOutlined />} />
            </Card>
          </Col>
        </Row>
      )}

      {seedError && (
        <Alert
          type="error"
          showIcon
          closable
          message="知识库初始化失败"
          description={seedError}
          onClose={() => setSeedError('')}
          style={{ marginBottom: 16 }}
        />
      )}

      {/* ── Filters ── */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} align="middle">
          <Col xs={24} sm={6}>
            <Input
              prefix={<SearchOutlined />}
              placeholder="搜索标题/内容/标签..."
              value={query}
              onChange={e => setQuery(e.target.value)}
              onPressEnter={() => handleSearch()}
              allowClear
            />
          </Col>
          <Col xs={12} sm={3}>
            <Select
              value={nodeType}
              onChange={v => setNodeType(v)}
              options={NODE_TYPE_OPTIONS}
              style={{ width: '100%' }}
              placeholder="节点类型"
            />
          </Col>
          <Col xs={12} sm={3}>
            <Select
              value={auditStatus}
              onChange={v => setAuditStatus(v)}
              options={AUDIT_STATUS_OPTIONS}
              style={{ width: '100%' }}
              placeholder="审核状态"
            />
          </Col>
          <Col xs={12} sm={5}>
            <Space>
              <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>最低可信度</Text>
              <Slider
                min={0} max={1} step={0.1}
                value={minTrust}
                onChange={v => setMinTrust(v as number)}
                style={{ width: 120, margin: 0 }}
                tooltip={{ formatter: v => `${(v as number * 100).toFixed(0)}%` }}
              />
            </Space>
          </Col>
          <Col xs={12} sm={4}>
            <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch} loading={loading}>
              搜索
            </Button>
          </Col>
          <Col xs={12} sm={3} style={{ textAlign: 'right' }}>
            {isAdmin && (
              <Space>
                {needingReviewCount > 0 && (
                  <Tag color="warning" icon={<SafetyCertificateOutlined />}>
                    {needingReviewCount} 待审核
                  </Tag>
                )}
                <Tooltip title="初始化/更新知识库种子数据">
                  <Button
                    size="small"
                    icon={<ReloadOutlined />}
                    loading={seeding}
                    onClick={handleSeed}
                  >
                    Seed
                  </Button>
                </Tooltip>
              </Space>
            )}
          </Col>
        </Row>
      </Card>

      {/* ── Results ── */}
      <Card size="small" title={`搜索结果 (${total} 条，当前第 ${page} 页)`}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 64 }}><Spin size="large" /></div>
        ) : results.length === 0 ? (
          <Empty description="未找到匹配的知识节点">
            {isAdmin && (
              <Button type="primary" onClick={handleSeed} loading={seeding}>
                初始化知识库
              </Button>
            )}
          </Empty>
        ) : (
          <>
            <List
              dataSource={results}
              renderItem={item => (
                <List.Item
                  key={item.id}
                  style={{ cursor: 'pointer' }}
                  onClick={() => openNodeDetail(item)}
                  extra={
                    <Space direction="vertical" size={2} style={{ textAlign: 'right' }}>
                      <Tag color={NODE_TYPE_COLORS[item.node_type] || 'default'}>
                        {NODE_TYPE_OPTIONS.find(o => o.value === item.node_type)?.label ?? item.node_type}
                      </Tag>
                      {item.rule_id && <Tag color="blue">{item.rule_id}</Tag>}
                    </Space>
                  }
                >
                  <List.Item.Meta
                    avatar={<span style={{ fontSize: 20 }}>{NODE_TYPE_ICONS[item.node_type] || <NodeIndexOutlined />}</span>}
                    title={
                      <Space>
                        <Text strong>{item.title}</Text>
                        {item.audit_status === 'verified' && (
                          <Tag color="success" style={{ fontSize: 10 }}>已审核</Tag>
                        )}
                        {item.audit_status === 'unreviewed' && (
                          <Tag color="warning" style={{ fontSize: 10 }}>未审核</Tag>
                        )}
                        <Tag style={{ fontSize: 10 }}>
                          可信度 {(item.trust_level * 100).toFixed(0)}%
                        </Tag>
                      </Space>
                    }
                    description={
                      <div>
                        <Paragraph ellipsis={{ rows: 1 }} style={{ marginBottom: 4 }}>
                          {item.content}
                        </Paragraph>
                        <Space size={4}>
                          {item.source && <Text type="secondary" style={{ fontSize: 12 }}>来源: {item.source}</Text>}
                          {item.jurisdiction && <Text type="secondary" style={{ fontSize: 12 }}>管辖: {item.jurisdiction}</Text>}
                        </Space>
                        <div style={{ marginTop: 4 }}>{tagColors(item.tags)}</div>
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
            {total > pageSize && (
              <div style={{ textAlign: 'center', marginTop: 16 }}>
                <Pagination
                  current={page}
                  pageSize={pageSize}
                  total={total}
                  onChange={p => doSearch(p)}
                  showSizeChanger={false}
                  showTotal={(t) => `共 ${t} 条`}
                />
              </div>
            )}
          </>
        )}
      </Card>

      {/* ── Node Detail Drawer ── */}
      <Drawer
        title={selectedNode?.title ?? '节点详情'}
        open={!!selectedNode}
        onClose={() => { setSelectedNode(null); setRelatedNodes([]); }}
        width={480}
      >
        {selectedNode && (
          <div>
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              {/* Meta */}
              <Card size="small" title="基本信息">
                <Row gutter={[8, 8]}>
                  <Col span={12}><Text type="secondary">类型</Text><br /><Tag color={NODE_TYPE_COLORS[selectedNode.node_type]}>{selectedNode.node_type}</Tag></Col>
                  <Col span={12}><Text type="secondary">可信度</Text><br /><Text>{selectedNode.trust_level}</Text></Col>
                  <Col span={12}><Text type="secondary">审核状态</Text><br /><Tag color={selectedNode.audit_status === 'verified' ? 'success' : selectedNode.audit_status === 'rejected' ? 'error' : selectedNode.audit_status === 'flagged' ? 'warning' : 'default'}>{selectedNode.audit_status}</Tag></Col>
                  <Col span={12}><Text type="secondary">来源</Text><br /><Text>{selectedNode.source || '-'}</Text></Col>
                  {selectedNode.rule_id && <Col span={12}><Text type="secondary">关联规则</Text><br /><Tag color="blue">{selectedNode.rule_id}</Tag></Col>}
                  {selectedNode.jurisdiction && <Col span={12}><Text type="secondary">管辖范围</Text><br /><Text>{selectedNode.jurisdiction}</Text></Col>}
                  {selectedNode.effective_date && <Col span={12}><Text type="secondary">生效日期</Text><br /><Text>{selectedNode.effective_date}</Text></Col>}
                </Row>
                <div style={{ marginTop: 8 }}>{tagColors(selectedNode.tags)}</div>
              </Card>
              <Card size="small" title="内容">
                <Paragraph style={{ whiteSpace: 'pre-wrap' }}>{selectedNode.content}</Paragraph>
              </Card>
              {/* Related */}
              <Card size="small" title={`关联节点${relatedLoading ? '' : ` (${relatedNodes.length})`}`}>
                {relatedLoading ? <Spin /> : relatedNodes.length === 0 ? (
                  <Text type="secondary">无关联节点</Text>
                ) : (
                  <List
                    size="small"
                    dataSource={relatedNodes}
                    renderItem={rel => (
                      <List.Item>
                        <List.Item.Meta
                          avatar={<span>{NODE_TYPE_ICONS[rel.node.node_type] || <NodeIndexOutlined />}</span>}
                          title={
                            <Space size={4}>
                              <Text>{rel.node.title}</Text>
                              <Tag>{rel.relation}</Tag>
                            </Space>
                          }
                          description={
                            <Text type="secondary" ellipsis>{rel.node.content}</Text>
                          }
                        />
                      </List.Item>
                    )}
                  />
                )}
              </Card>
            </Space>
          </div>
        )}
      </Drawer>
    </div>
  );
};

export default KGGraph;
