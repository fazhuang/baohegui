/**
 * KGCases — 案例库页
 *
 * 路由: /kg/cases
 * 功能: 案例搜索、标签/风险类型筛选、案例详情、关联规则/法规展示
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  Input, Select, Row, Col, Card, List, Tag,
  Drawer, Button, Space, Typography, Spin, Empty,
} from 'antd';
import {
  SearchOutlined, FolderOpenOutlined, SettingOutlined,
  ReadOutlined, NodeIndexOutlined,
} from '@ant-design/icons';
import { searchKG, getRelatedNodes } from '../services/api';
import type { KGNode, KGRelatedNode } from '../services/api';

const { Text, Paragraph } = Typography;

// Common case tags for quick filtering
const CASE_TAG_OPTIONS = [
  { label: '全部', value: '' },
  { label: '品牌锁定', value: '品牌锁定' },
  { label: '参数排他', value: '参数排他' },
  { label: '厂家授权', value: '厂家授权' },
  { label: '资质超标', value: '资质超标' },
  { label: '业绩要求', value: '业绩要求' },
  { label: '评分标准', value: '评分标准' },
  { label: '投诉成立', value: '投诉成立' },
  { label: '参数指向', value: '参数指向' },
  { label: '中小企业', value: '中小企业' },
  { label: '异常低价', value: '异常低价' },
];

const JURISDICTION_OPTIONS = [
  { label: '全部', value: '' },
  { label: '甘肃', value: '甘肃' },
  { label: '宁夏', value: '宁夏' },
  { label: '四川', value: '四川' },
  { label: '全国', value: '全国' },
];

const KGCases: React.FC = () => {
  const [query, setQuery] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [jurisdiction, setJurisdiction] = useState('');

  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<KGNode[]>([]);
  const [total, setTotal] = useState(0);

  const [selectedNode, setSelectedNode] = useState<KGNode | null>(null);
  const [relatedNodes, setRelatedNodes] = useState<KGRelatedNode[]>([]);
  const [relatedLoading, setRelatedLoading] = useState(false);

  const doSearch = useCallback(async () => {
    setLoading(true);
    try {
      const res = await searchKG({
        q: query || '',
        node_type: 'case',
        tags: tagFilter || undefined,
        jurisdiction: jurisdiction || undefined,
        limit: 50,
      });
      setResults(res.results);
      setTotal(res.total);
    } catch {
      // handled by interceptor
    } finally {
      setLoading(false);
    }
  }, [query, tagFilter, jurisdiction]);

  useEffect(() => {
    doSearch();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const openDetail = useCallback(async (node: KGNode) => {
    setSelectedNode(node);
    setRelatedLoading(true);
    try {
      // 案例节点是边上的 target，用 incoming 查询以找到引用它的 rule
      const rel = await getRelatedNodes(node.id, undefined, "incoming");
      setRelatedNodes(rel.related);
    } catch {
      setRelatedNodes([]);
    } finally {
      setRelatedLoading(false);
    }
  }, []);

  const tagColors = (tags: string) => {
    return (tags || '').split(',').filter(Boolean).map((t, i) => {
      const color = t === '投诉成立' ? 'error' : t === '投诉驳回' ? 'warning' : 'default';
      return <Tag key={i} color={color} style={{ marginBottom: 2 }}>{t.trim()}</Tag>;
    });
  };

  const relationColors = (rel: string) => {
    if (rel === 'demonstrated_by') return 'orange';
    if (rel === 'references') return 'blue';
    return 'default';
  };

  return (
    <div>
      {/* ── Filters ── */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} align="middle">
          <Col xs={24} sm={6}>
            <Input
              prefix={<SearchOutlined />}
              placeholder="搜索案例标题/内容..."
              value={query}
              onChange={e => setQuery(e.target.value)}
              onPressEnter={doSearch}
              allowClear
            />
          </Col>
          <Col xs={12} sm={4}>
            <Select
              value={tagFilter}
              onChange={v => setTagFilter(v)}
              options={CASE_TAG_OPTIONS}
              style={{ width: '100%' }}
              placeholder="风险类型"
              showSearch
            />
          </Col>
          <Col xs={12} sm={4}>
            <Select
              value={jurisdiction}
              onChange={v => setJurisdiction(v)}
              options={JURISDICTION_OPTIONS}
              style={{ width: '100%' }}
              placeholder="管辖范围"
            />
          </Col>
          <Col xs={12} sm={4}>
            <Button type="primary" icon={<SearchOutlined />} onClick={doSearch} loading={loading}>
              搜索
            </Button>
          </Col>
          <Col xs={12} sm={6} style={{ textAlign: 'right' }}>
            {total > 0 && (
              <Text type="secondary">共 {total} 个案例</Text>
            )}
          </Col>
        </Row>
      </Card>

      {/* ── Results ── */}
      <Card size="small" title={`案例列表 (${results.length})`}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 64 }}><Spin size="large" /></div>
        ) : results.length === 0 ? (
          <Empty description="未找到匹配的案例" />
        ) : (
          <List
            dataSource={results}
            renderItem={item => (
              <List.Item
                key={item.id}
                style={{ cursor: 'pointer' }}
                onClick={() => openDetail(item)}
              >
                <List.Item.Meta
                  avatar={<FolderOpenOutlined style={{ fontSize: 20, color: '#fa8c16' }} />}
                  title={
                    <Space size={8}>
                      <Text strong>{item.title}</Text>
                      {item.audit_status === 'verified' && (
                        <Tag color="success" style={{ fontSize: 10 }}>已审核</Tag>
                      )}
                    </Space>
                  }
                  description={
                    <div>
                      <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 4 }}>
                        {item.content}
                      </Paragraph>
                      <Space size={4}>
                        {item.source && <Text type="secondary" style={{ fontSize: 12 }}>来源: {item.source}</Text>}
                        {item.jurisdiction && <Text type="secondary" style={{ fontSize: 12 }}>· {item.jurisdiction}</Text>}
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          · 可信度 {(item.trust_level * 100).toFixed(0)}%
                        </Text>
                      </Space>
                      <div style={{ marginTop: 4 }}>{tagColors(item.tags)}</div>
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      {/* ── Detail Drawer ── */}
      <Drawer
        title={selectedNode?.title ?? '案例详情'}
        open={!!selectedNode}
        onClose={() => { setSelectedNode(null); setRelatedNodes([]); }}
        width={480}
      >
        {selectedNode && (
          <div>
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <Card size="small" title="案例信息">
                <Row gutter={[8, 8]}>
                  <Col span={12}><Text type="secondary">来源</Text><br /><Text>{selectedNode.source || '-'}</Text></Col>
                  <Col span={12}><Text type="secondary">管辖</Text><br /><Text>{selectedNode.jurisdiction || '-'}</Text></Col>
                  <Col span={12}><Text type="secondary">可信度</Text><br /><Text>{(selectedNode.trust_level * 100).toFixed(0)}%</Text></Col>
                  <Col span={12}><Text type="secondary">审核状态</Text><br />
                    <Tag color={selectedNode.audit_status === 'verified' ? 'success' : 'default'}>
                      {selectedNode.audit_status}
                    </Tag>
                  </Col>
                </Row>
                <div style={{ marginTop: 8 }}>{tagColors(selectedNode.tags)}</div>
              </Card>

              <Card size="small" title="案例内容">
                <Paragraph style={{ whiteSpace: 'pre-wrap' }}>{selectedNode.content}</Paragraph>
              </Card>

              {/* Related rules and regulations */}
              <Card size="small" title={`关联规则与法规${relatedLoading ? '' : ` (${relatedNodes.length})`}`}>
                {relatedLoading ? <Spin /> : relatedNodes.length === 0 ? (
                  <Text type="secondary">暂无关联规则</Text>
                ) : (
                  <List
                    size="small"
                    dataSource={relatedNodes}
                    renderItem={rel => (
                      <List.Item>
                        <List.Item.Meta
                          avatar={
                            rel.node.node_type === 'rule'
                              ? <SettingOutlined style={{ color: '#52c41a' }} />
                              : rel.node.node_type === 'regulation'
                              ? <ReadOutlined style={{ color: '#1677ff' }} />
                              : <NodeIndexOutlined />
                          }
                          title={
                            <Space size={4}>
                              <Text>{rel.node.title}</Text>
                              <Tag color={relationColors(rel.relation)}>{rel.relation}</Tag>
                            </Space>
                          }
                          description={
                            <div>
                              <Text type="secondary" ellipsis>{rel.node.content}</Text>
                              {rel.node.rule_id && (
                                <div><Tag color="blue" style={{ marginTop: 4 }}>{rel.node.rule_id}</Tag></div>
                              )}
                            </div>
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

export default KGCases;
