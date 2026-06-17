/**
 * KGLegal — 法规库页
 *
 * 路由: /kg/legal
 * 功能: 法规/平台规则搜索、来源/平台/标签筛选、关联规则展示
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  Input, Select, Row, Col, Card, List, Tag,
  Drawer, Button, Space, Typography, Spin, Empty, Pagination,
} from 'antd';
import {
  SearchOutlined, ReadOutlined,
  FolderOpenOutlined, SettingOutlined,
} from '@ant-design/icons';
import { searchKG, getRelatedNodes } from '../services/api';
import type { KGNode, KGRelatedNode } from '../services/api';

const { Text, Paragraph } = Typography;

const SOURCE_OPTIONS = [
  { label: '全部', value: '' },
  { label: '全国人大', value: '全国人大' },
  { label: '国务院', value: '国务院' },
  { label: '财政部', value: '财政部' },
  { label: '甘肃平台', value: '甘肃' },
  { label: '广东平台', value: '广东' },
  { label: '江苏平台', value: '江苏' },
  { label: '四川平台', value: '四川' },
  { label: '浙江平台', value: '浙江' },
];

const TAG_OPTIONS = [
  { label: '全部', value: '' },
  { label: '核心法规', value: '核心法规' },
  { label: '部门规章', value: '部门规章' },
  { label: '行政法规', value: '行政法规' },
  { label: '平台规则', value: '平台规则' },
  { label: '基础法规', value: '基础法规' },
  { label: '政府采购', value: '政府采购' },
  { label: '招标投标', value: '招标投标' },
];

const KGLegal: React.FC = () => {
  const [query, setQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [tagFilter, setTagFilter] = useState('');

  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<KGNode[]>([]);
  const [total, setTotal] = useState(0);

  // Pagination
  const pageSize = 50;
  const [page, setPage] = useState(1);

  const [selectedNode, setSelectedNode] = useState<KGNode | null>(null);
  const [relatedNodes, setRelatedNodes] = useState<KGRelatedNode[]>([]);
  const [relatedLoading, setRelatedLoading] = useState(false);

  const doSearch = useCallback(async (searchPage: number = 1) => {
    setLoading(true);
    try {
      const offset = (searchPage - 1) * pageSize;
      const res = await searchKG({
        q: query || '',
        node_type: 'regulation',
        jurisdiction: sourceFilter || undefined,
        tags: tagFilter || undefined,
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
  }, [query, sourceFilter, tagFilter]);

  // Search with filter reset to page 1
  const handleSearch = useCallback(() => {
    doSearch(1);
  }, [doSearch]);

  useEffect(() => {
    handleSearch();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const openDetail = useCallback(async (node: KGNode) => {
    setSelectedNode(node);
    setRelatedLoading(true);
    try {
      // 法规节点是边上的 target，用 incoming 查询以找到引用它的 rule
      const rel = await getRelatedNodes(node.id, undefined, "incoming");
      setRelatedNodes(rel.related);
    } catch {
      setRelatedNodes([]);
    } finally {
      setRelatedLoading(false);
    }
  }, []);

  const tagColors = (tags: string) => {
    return (tags || '').split(',').filter(Boolean).map((t, i) => (
      <Tag key={i} color="blue" style={{ marginBottom: 2 }}>{t.trim()}</Tag>
    ));
  };

  const relationLabel = (rel: string) => {
    const map: Record<string, string> = {
      references: '被引用',
      demonstrated_by: '案例证实',
      mitigated_by: '整改建议',
    };
    return map[rel] || rel;
  };

  return (
    <div>
      {/* ── Filters ── */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} align="middle">
          <Col xs={24} sm={6}>
            <Input
              prefix={<SearchOutlined />}
              placeholder="搜索法规名称/内容..."
              value={query}
              onChange={e => setQuery(e.target.value)}
              onPressEnter={() => handleSearch()}
              allowClear
            />
          </Col>
          <Col xs={12} sm={4}>
            <Select
              value={sourceFilter}
              onChange={v => setSourceFilter(v)}
              options={SOURCE_OPTIONS}
              style={{ width: '100%' }}
              placeholder="来源机构"
              showSearch
            />
          </Col>
          <Col xs={12} sm={4}>
            <Select
              value={tagFilter}
              onChange={v => setTagFilter(v)}
              options={TAG_OPTIONS}
              style={{ width: '100%' }}
              placeholder="法规类型"
            />
          </Col>
          <Col xs={12} sm={4}>
            <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch} loading={loading}>
              搜索
            </Button>
          </Col>
          <Col xs={12} sm={6} style={{ textAlign: 'right' }}>
            {total > 0 && (
              <Text type="secondary">共 {total} 条法规</Text>
            )}
          </Col>
        </Row>
      </Card>

      {/* ── Results ── */}
      <Card size="small" title={`法规列表 (${total} 条，当前第 ${page} 页)`}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 64 }}><Spin size="large" /></div>
        ) : results.length === 0 ? (
          <Empty description="未找到匹配的法规" />
        ) : (
          <>
            <List
              dataSource={results}
              renderItem={item => (
                <List.Item
                  key={item.id}
                  style={{ cursor: 'pointer' }}
                  onClick={() => openDetail(item)}
                >
                  <List.Item.Meta
                    avatar={<ReadOutlined style={{ fontSize: 20, color: '#1677ff' }} />}
                    title={
                      <Space size={8}>
                        <Text strong>{item.title}</Text>
                        {item.audit_status === 'verified' && (
                          <Tag color="success" style={{ fontSize: 10 }}>已审核</Tag>
                        )}
                        {item.rule_id && (
                          <Tag color="blue" style={{ fontSize: 10 }}>{item.rule_id}</Tag>
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
                          {item.effective_date && <Text type="secondary" style={{ fontSize: 12 }}>· 生效: {item.effective_date}</Text>}
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

      {/* ── Detail Drawer ── */}
      <Drawer
        title={selectedNode?.title ?? '法规详情'}
        open={!!selectedNode}
        onClose={() => { setSelectedNode(null); setRelatedNodes([]); }}
        width={480}
      >
        {selectedNode && (
          <div>
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <Card size="small" title="法规信息">
                <Row gutter={[8, 8]}>
                  <Col span={12}><Text type="secondary">来源机构</Text><br /><Text>{selectedNode.source || '-'}</Text></Col>
                  <Col span={12}><Text type="secondary">管辖范围</Text><br /><Text>{selectedNode.jurisdiction || '-'}</Text></Col>
                  <Col span={12}><Text type="secondary">生效日期</Text><br /><Text>{selectedNode.effective_date || '-'}</Text></Col>
                  <Col span={12}><Text type="secondary">发布日期</Text><br /><Text>{selectedNode.publish_date || '-'}</Text></Col>
                  <Col span={12}>
                    <Text type="secondary">可信度</Text><br />
                    <Text>{(selectedNode.trust_level * 100).toFixed(0)}%</Text>
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">审核状态</Text><br />
                    <Tag color={selectedNode.audit_status === 'verified' ? 'success' : 'default'}>
                      {selectedNode.audit_status}
                    </Tag>
                  </Col>
                </Row>
                <div style={{ marginTop: 8 }}>{tagColors(selectedNode.tags)}</div>
              </Card>

              <Card size="small" title="法规内容">
                <Paragraph style={{ whiteSpace: 'pre-wrap' }}>{selectedNode.content}</Paragraph>
              </Card>

              {/* Related: rules that reference this regulation */}
              <Card size="small" title={`关联规则 (${relatedNodes.length})`}>
                {relatedLoading ? <Spin /> : relatedNodes.length === 0 ? (
                  <Text type="secondary">暂无规则引用此法规</Text>
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
                              : <FolderOpenOutlined style={{ color: '#fa8c16' }} />
                          }
                          title={
                            <Space size={4}>
                              <Text>{rel.node.title}</Text>
                              <Tag color="green">{relationLabel(rel.relation)}</Tag>
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

export default KGLegal;
