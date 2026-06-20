/**
 * AdminCaseReviewTab — 案例审核队列
 *
 * Phase 2: 管理员审核采集案例，支持原文/脱敏对照、字段编辑、审核操作
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button, Card, Col, Drawer, Input, Modal, Pagination, Row,
  Select, Space, Statistic, Table, Tag, Typography, message, Descriptions,
  Collapse,
} from 'antd';
import {
  CheckOutlined, CloseOutlined,
  EyeOutlined, SearchOutlined, StopOutlined, ReloadOutlined,
  LockOutlined, FileTextOutlined, WarningOutlined,
  SwapOutlined,
} from '@ant-design/icons';
import {
  getReviewQueue, getReviewQueueStats, getCaseDetail,
  updateCase, reviewCases, dedupCheckCase,
} from '../../../services/api';
import type { ComplaintCaseItem, ComplaintCaseDetail, ReviewQueueStats } from '../../../types';

const { Text, Paragraph } = Typography;

const CASE_STATUS_OPTIONS = [
  { label: '全部待处理', value: '' },
  { label: '待审核', value: 'pending_review' },
  { label: '已抽取', value: 'extracted' },
  { label: '已抓取', value: 'fetched' },
  { label: '已规范化', value: 'normalized' },
  { label: '审核通过', value: 'verified' },
  { label: '隔离', value: 'quarantined' },
  { label: '解析失败', value: 'parse_failed' },
  { label: '已拒绝', value: 'rejected' },
  { label: '重复', value: 'duplicate' },
];

const ACTIONS_MAP: Record<string, { label: string; color: string }> = {
  fetched: { label: '已抓取', color: 'default' },
  normalized: { label: '已规范化', color: 'processing' },
  extracted: { label: '已抽取', color: 'purple' },
  pending_review: { label: '待审核', color: 'orange' },
  verified: { label: '审核通过', color: 'cyan' },
  published: { label: '已发布', color: 'green' },
  duplicate: { label: '重复', color: 'magenta' },
  rejected: { label: '已拒绝', color: 'red' },
  parse_failed: { label: '解析失败', color: 'error' },
  quarantined: { label: '隔离', color: 'warning' },
  archived: { label: '已归档', color: 'default' },
  unpublished: { label: '已下架', color: 'volcano' },
};

const AdminCaseReviewTab: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [cases, setCases] = useState<ComplaintCaseItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(30);

  // Filters
  const [statusFilter, setStatusFilter] = useState('');
  const [searchText, setSearchText] = useState('');

  // Stats
  const [stats, setStats] = useState<ReviewQueueStats | null>(null);

  // Detail
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<ComplaintCaseDetail | null>(null);

  // Edit mode
  const [editMode, setEditMode] = useState(false);
  const [editFields, setEditFields] = useState<Record<string, unknown>>({});

  // Review
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [batchAction, setBatchAction] = useState<string>('');
  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [reviewReason, setReviewReason] = useState('');
  const [reviewSingleId, setReviewSingleId] = useState<number | null>(null);
  const [reviewSingleAction, setReviewSingleAction] = useState('');

  // Dedup
  const [dedupModal, setDedupModal] = useState(false);
  const [dedupResult, setDedupResult] = useState<Record<string, unknown> | null>(null);

  // Load queue
  const loadQueue = useCallback(async (p: number = 1) => {
    setLoading(true);
    try {
      const res = await getReviewQueue({
        review_status: statusFilter || undefined,
        search: searchText || undefined,
        limit: pageSize,
        offset: (p - 1) * pageSize,
        sort_by: 'created_at',
        sort_dir: 'desc',
      });
      setCases(res.cases);
      setTotal(res.total);
      setPage(p);
    } catch {
      // handled by interceptor
    } finally {
      setLoading(false);
    }
  }, [statusFilter, searchText, pageSize]);

  // Load stats
  const loadStats = useCallback(async () => {
    try {
      const res = await getReviewQueueStats();
      setStats(res);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadQueue(1);
    loadStats();
  }, []); // eslint-disable-line

  const handleSearch = () => loadQueue(1);

  // Open detail
  const openDetail = useCallback(async (id: number) => {
    setDrawerOpen(true);
    setDetailLoading(true);
    setEditMode(false);
    setEditFields({});
    try {
      const d = await getCaseDetail(id);
      setDetail(d);
    } catch {
      // handled
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // Save edits
  const saveEdits = useCallback(async () => {
    if (!detail || Object.keys(editFields).length === 0) return;
    try {
      await updateCase(detail.id, editFields);
      message.success(`已更新 ${Object.keys(editFields).length} 个字段`);
      setEditMode(false);
      setEditFields({});
      // Reload detail
      openDetail(detail.id);
    } catch {
      message.error('更新失败');
    }
  }, [detail, editFields, openDetail]);

  // Single review action
  const doSingleReview = useCallback(async () => {
    if (!reviewSingleId || !reviewSingleAction) return;
    try {
      const res = await reviewCases({
        action: reviewSingleAction,
        reason: reviewReason,
        case_ids: [reviewSingleId],
        mark_published: reviewSingleAction === 'approve',
      });
      if (res.success_count > 0) {
        message.success(`操作成功: ${res.results[0]?.from_status} → ${res.results[0]?.to_status}`);
      }
      if (res.error_count > 0) {
        message.error(res.errors.map((e: { case_id: number; error: string }) => e.error).join('; '));
      }
      setReviewModalOpen(false);
      setReviewReason('');
      setReviewSingleId(null);
      setReviewSingleAction('');
      loadQueue(page);
      if (drawerOpen) openDetail(detail?.id ?? 0);
    } catch {
      message.error('操作失败');
    }
  }, [reviewSingleId, reviewSingleAction, reviewReason, page, drawerOpen, detail, loadQueue, openDetail]);

  // Batch review
  const doBatchReview = useCallback(async () => {
    if (selectedRowKeys.length === 0 || !batchAction) return;
    try {
      const res = await reviewCases({
        action: batchAction,
        reason: reviewReason,
        case_ids: selectedRowKeys.map(Number),
        mark_published: batchAction === 'approve',
      });
      message.success(`批量操作完成: 成功 ${res.success_count}, 失败 ${res.error_count}`);
      setSelectedRowKeys([]);
      setBatchAction('');
      setReviewReason('');
      setReviewModalOpen(false);
      loadQueue(page);
    } catch {
      message.error('批量操作失败');
    }
  }, [selectedRowKeys, batchAction, reviewReason, page, loadQueue]);

  // Dedup check
  const doDedupCheck = useCallback(async (caseId: number) => {
    try {
      const res = await dedupCheckCase(caseId, false);
      setDedupResult(res);
      setDedupModal(true);
    } catch {
      message.error('去重检查失败');
    }
  }, []);

  // Columns
  const columns = useMemo(() => [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 60,
    },
    {
      title: '标题',
      dataIndex: 'title',
      ellipsis: true,
      width: 280,
    },
    {
      title: '状态',
      dataIndex: 'review_status',
      width: 100,
      render: (s: string) => {
        const info = ACTIONS_MAP[s] || { label: s, color: 'default' };
        return <Tag color={info.color}>{info.label}</Tag>;
      },
    },
    {
      title: '省份',
      dataIndex: 'province',
      width: 80,
    },
    {
      title: '决定类型',
      dataIndex: 'decision_type',
      width: 100,
    },
    {
      title: '质量',
      dataIndex: 'quality_score',
      width: 70,
      render: (s: number) => s ? (s * 100).toFixed(0) + '%' : '-',
    },
    {
      title: '内容',
      width: 100,
      render: (_: unknown, r: ComplaintCaseItem) => (
        <Space size={4}>
          {r.has_raw ? <Tag color="blue" style={{ fontSize: 10 }}>原文</Tag> : null}
          {r.has_sanitized ? <Tag color="green" style={{ fontSize: 10 }}>脱敏</Tag> : null}
        </Space>
      ),
    },
    {
      title: '可操作',
      dataIndex: 'allowed_transitions',
      width: 150,
      render: (transitions: string[]) => (
        <Space size={4} wrap>
          {transitions.map((t: string) => {
            const info = ACTIONS_MAP[t] || { label: t, color: 'default' };
            return <Tag key={t} color={info.color} style={{ fontSize: 10 }}>{info.label}</Tag>;
          })}
        </Space>
      ),
    },
    {
      title: '操作',
      width: 200,
      fixed: 'right' as const,
      render: (_: unknown, r: ComplaintCaseItem) => (
        <Space size={4}>
          <Button size="small" icon={<EyeOutlined />} onClick={() => openDetail(r.id)}>详情</Button>
          {r.allowed_transitions.includes('verified') && (
            <Button size="small" type="primary" icon={<CheckOutlined />}
              onClick={() => { setReviewSingleId(r.id); setReviewSingleAction('approve'); setReviewReason(''); setReviewModalOpen(true); }}>
              通过
            </Button>
          )}
          {r.allowed_transitions.includes('rejected') && (
            <Button size="small" danger icon={<CloseOutlined />}
              onClick={() => { setReviewSingleId(r.id); setReviewSingleAction('reject'); setReviewReason(''); setReviewModalOpen(true); }}>
              拒绝
            </Button>
          )}
          <Button size="small" icon={<SwapOutlined />} onClick={() => doDedupCheck(r.id)}>去重</Button>
        </Space>
      ),
    },
  ], [openDetail, doDedupCheck]);

  // Row selection
  const rowSelection = {
    selectedRowKeys,
    onChange: (keys: React.Key[]) => setSelectedRowKeys(keys),
  };

  return (
    <div>
      {/* Stats bar */}
      {stats && (
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={12} sm={6}><Card size="small"><Statistic title="待审核" value={stats.pending_total} valueStyle={{ color: '#fa8c16' }} /></Card></Col>
          <Col xs={12} sm={6}><Card size="small"><Statistic title="已发布" value={stats.by_status?.published ?? 0} valueStyle={{ color: '#52c41a' }} /></Card></Col>
          <Col xs={12} sm={6}><Card size="small"><Statistic title="已拒绝" value={stats.by_status?.rejected ?? 0} valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
          <Col xs={12} sm={6}><Card size="small"><Statistic title="隔离" value={stats.by_status?.quarantined ?? 0} valueStyle={{ color: '#faad14' }} /></Card></Col>
        </Row>
      )}

      {/* Filters */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} align="middle">
          <Col xs={24} sm={4}>
            <Select
              value={statusFilter}
              onChange={v => { setStatusFilter(v); }}
              options={CASE_STATUS_OPTIONS}
              style={{ width: '100%' }}
              placeholder="状态"
              allowClear
            />
          </Col>
          <Col xs={24} sm={6}>
            <Input
              prefix={<SearchOutlined />}
              placeholder="搜索标题/项目..."
              value={searchText}
              onChange={e => setSearchText(e.target.value)}
              onPressEnter={handleSearch}
              allowClear
            />
          </Col>
          <Col xs={12} sm={4}>
            <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch} loading={loading}>查询</Button>
            <Button style={{ marginLeft: 8 }} icon={<ReloadOutlined />} onClick={() => loadQueue(page)} />
          </Col>
          <Col xs={12} sm={10} style={{ textAlign: 'right' }}>
            {selectedRowKeys.length > 0 && (
              <Space>
                <Text>{selectedRowKeys.length} 条已选</Text>
                <Select
                  value={batchAction}
                  onChange={v => { setBatchAction(v); setReviewReason(''); setReviewModalOpen(true); }}
                  placeholder="批量操作"
                  style={{ width: 150 }}
                  options={[
                    { label: '审核通过', value: 'approve' },
                    { label: '拒绝', value: 'reject' },
                    { label: '隔离', value: 'quarantine' },
                    { label: '标记重复', value: 'mark_duplicate' },
                  ]}
                />
              </Space>
            )}
          </Col>
        </Row>
      </Card>

      {/* Table */}
      <Card size="small" title={`审核队列 (${total} 条)`}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={cases}
          loading={loading}
          size="small"
          scroll={{ x: 1100 }}
          rowSelection={rowSelection}
          pagination={false}
          onRow={r => ({
            style: { cursor: 'pointer' },
            onDoubleClick: () => openDetail(r.id),
          })}
        />
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Pagination
            current={page}
            pageSize={pageSize}
            total={total}
            onChange={p => loadQueue(p)}
            showSizeChanger={false}
            showTotal={t => `共 ${t} 条`}
          />
        </div>
      </Card>

      {/* Detail Drawer */}
      <Drawer
        title={
          <Space>
            <span>案例详情</span>
            {detail && (
              <Tag color={ACTIONS_MAP[detail.review_status]?.color}>
                {ACTIONS_MAP[detail.review_status]?.label}
              </Tag>
            )}
          </Space>
        }
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setDetail(null); setEditMode(false); setEditFields({}); }}
        width={640}
        extra={
          !editMode ? (
            <Space>
              <Button icon={<SwapOutlined />} onClick={() => detail && doDedupCheck(detail.id)}>去重</Button>
              <Button onClick={() => { setEditMode(true); setEditFields({}); }}>编辑</Button>
            </Space>
          ) : (
            <Space>
              <Button onClick={() => setEditMode(false)}>取消</Button>
              <Button type="primary" onClick={saveEdits}>保存</Button>
            </Space>
          )
        }
      >
        {detailLoading ? (
          <div style={{ textAlign: 'center', padding: 64 }}>加载中...</div>
        ) : detail ? (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {/* Basic info */}
            <Card size="small" title="基本信息">
              {!editMode ? (
                <Descriptions column={2} size="small">
                  <Descriptions.Item label="标题" span={2}>{detail.title}</Descriptions.Item>
                  <Descriptions.Item label="省份">{detail.province || '-'}</Descriptions.Item>
                  <Descriptions.Item label="城市">{detail.city || '-'}</Descriptions.Item>
                  <Descriptions.Item label="项目名称">{detail.project_name || '-'}</Descriptions.Item>
                  <Descriptions.Item label="项目编号">{detail.project_number || '-'}</Descriptions.Item>
                  <Descriptions.Item label="案件编号">{detail.case_no || '-'}</Descriptions.Item>
                  <Descriptions.Item label="决定日期">{detail.decision_date || '-'}</Descriptions.Item>
                  <Descriptions.Item label="决定类型">{detail.decision_type}</Descriptions.Item>
                  <Descriptions.Item label="投诉人" span={2}>{detail.complainant || '-'}</Descriptions.Item>
                  <Descriptions.Item label="被投诉人" span={2}>{detail.respondent || '-'}</Descriptions.Item>
                  <Descriptions.Item label="投诉类型" span={2}>
                    {(detail.complaint_types || []).map((t: string) => <Tag key={t}>{t}</Tag>)}
                  </Descriptions.Item>
                  <Descriptions.Item label="法规依据" span={2}>
                    {(detail.legal_basis || []).map((b: string, i: number) => <Tag key={i}>{b}</Tag>)}
                  </Descriptions.Item>
                  <Descriptions.Item label="质量评分">{detail.quality_score ? (detail.quality_score * 100).toFixed(0) + '%' : '-'}</Descriptions.Item>
                  <Descriptions.Item label="来源类型">{detail.source_type || '-'}</Descriptions.Item>
                  {detail.canonical_url && (
                    <Descriptions.Item label="权威URL" span={2}>
                      <Text copyable ellipsis style={{ maxWidth: 400 }}>{detail.canonical_url}</Text>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              ) : (
                <Space direction="vertical" size="small" style={{ width: '100%' }}>
                  <Text strong>编辑模式 — 修改需要保存的字段后点击"保存"</Text>
                  {[
                    { key: 'title', label: '标题' },
                    { key: 'project_name', label: '项目名称' },
                    { key: 'project_number', label: '项目编号' },
                    { key: 'case_no', label: '案件编号' },
                    { key: 'city', label: '城市' },
                    { key: 'decision_type', label: '决定类型' },
                    { key: 'province', label: '省份' },
                  ].map(f => (
                    <div key={f.key}>
                      <Text type="secondary">{f.label}</Text>
                      <Input
                        defaultValue={(detail as unknown as Record<string, unknown>)[f.key] as string}
                        onChange={e => setEditFields(p => ({ ...p, [f.key]: e.target.value }))}
                        style={{ marginTop: 4 }}
                      />
                    </div>
                  ))}
                </Space>
              )}
            </Card>

            {/* Content comparison */}
            <Card size="small" title={
              <Space>
                <FileTextOutlined />
                <span>内容对照</span>
                {detail.has_raw && <Tag color="blue">原文</Tag>}
                {detail.has_raw && detail.sanitized_content && <Tag color="green">已脱敏</Tag>}
              </Space>
            }>
              <Collapse
                items={[
                  {
                    key: 'sanitized',
                    label: <span style={{ color: '#52c41a' }}>脱敏内容 (sanitized_content)</span>,
                    children: editMode ? (
                      <Input.TextArea
                        rows={6}
                        defaultValue={detail.sanitized_content || ''}
                        onChange={e => setEditFields(p => ({ ...p, sanitized_content: e.target.value }))}
                      />
                    ) : (
                      <Paragraph style={{ whiteSpace: 'pre-wrap' }}>
                        {detail.sanitized_content || detail.summary || '(无脱敏内容)'}
                      </Paragraph>
                    ),
                  },
                  {
                    key: 'raw',
                    label: <span style={{ color: '#1677ff' }}>原始内容 (raw_content) — 仅管理员可见</span>,
                    children: (
                      <Paragraph style={{ whiteSpace: 'pre-wrap', maxHeight: 400, overflow: 'auto' }}>
                        {detail.raw_content || '(无原始内容)'}
                      </Paragraph>
                    ),
                  },
                  {
                    key: 'summary',
                    label: '摘要',
                    children: (
                      <Paragraph style={{ whiteSpace: 'pre-wrap' }}>
                        {detail.summary || '(无摘要)'}
                      </Paragraph>
                    ),
                  },
                ]}
              />
            </Card>

            {/* Extraction metadata */}
            {detail.extraction_metadata && Object.keys(detail.extraction_metadata).length > 0 && (
              <Card size="small" title="LLM 抽取结果">
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="置信度">
                    {((detail.extraction_metadata.confidence as number) * 100)?.toFixed(0) ?? '?'}%
                  </Descriptions.Item>
                  <Descriptions.Item label="争议焦点">
                    {((detail.extraction_metadata.dispute_focus as string[]) || []).map((f: string, i: number) => (
                      <Tag key={i} color="orange">{f}</Tag>
                    ))}
                  </Descriptions.Item>
                  <Descriptions.Item label="监管认定">
                    {detail.extraction_metadata.regulatory_finding as string || '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="处理结果">
                    {detail.extraction_metadata.decision_result as string || '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="合规启示">
                    {((detail.extraction_metadata.compliance_insights as string[]) || []).map((f: string, i: number) => (
                      <Tag key={i} color="green">{f}</Tag>
                    ))}
                  </Descriptions.Item>
                  <Descriptions.Item label="风险标签">
                    {((detail.extraction_metadata.risk_tags as string[]) || []).map((f: string, i: number) => (
                      <Tag key={i} color="red">{f}</Tag>
                    ))}
                  </Descriptions.Item>
                  <Descriptions.Item label="证据片段">
                    <Collapse size="small" items={
                      ((detail.extraction_metadata.evidence_snippets as string[]) || []).map((s: string, i: number) => ({
                        key: String(i),
                        label: `证据${i + 1}`,
                        children: <Text style={{ whiteSpace: 'pre-wrap' }}>{s}</Text>,
                      }))
                    } />
                  </Descriptions.Item>
                </Descriptions>
              </Card>
            )}

            {/* Allowed transitions */}
            {detail.allowed_transitions && detail.allowed_transitions.length > 0 && (
              <Card size="small" title="可用操作">
                <Space wrap>
                  {detail.allowed_transitions.includes('verified') && (
                    <Button type="primary" icon={<CheckOutlined />}
                      onClick={() => { setReviewSingleId(detail.id); setReviewSingleAction('approve'); setReviewReason(''); setReviewModalOpen(true); }}>
                      审核通过
                    </Button>
                  )}
                  {detail.allowed_transitions.includes('rejected') && (
                    <Button danger icon={<CloseOutlined />}
                      onClick={() => { setReviewSingleId(detail.id); setReviewSingleAction('reject'); setReviewReason(''); setReviewModalOpen(true); }}>
                      拒绝
                    </Button>
                  )}
                  {detail.allowed_transitions.includes('quarantined') && (
                    <Button icon={<LockOutlined />}
                      onClick={() => { setReviewSingleId(detail.id); setReviewSingleAction('quarantine'); setReviewReason(''); setReviewModalOpen(true); }}>
                      隔离
                    </Button>
                  )}
                  {detail.allowed_transitions.includes('unpublished') && (
                    <Button danger icon={<StopOutlined />}
                      onClick={() => { setReviewSingleId(detail.id); setReviewSingleAction('unpublish'); setReviewReason(''); setReviewModalOpen(true); }}>
                      下架
                    </Button>
                  )}
                  {detail.allowed_transitions.includes('fetched') && (
                    <Button icon={<ReloadOutlined />}
                      onClick={() => { setReviewSingleId(detail.id); setReviewSingleAction('retry'); setReviewReason('重新处理'); setReviewModalOpen(true); }}>
                      重新处理
                    </Button>
                  )}
                </Space>
              </Card>
            )}

            {/* Candidate rules */}
            {detail.candidate_rules && detail.candidate_rules.length > 0 && (
              <Card size="small" title={`关联候选规则 (${detail.candidate_rules.length})`}>
                {detail.candidate_rules.map((r: { id: number; candidate_id: string; description: string; review_status: string; confidence: number }) => (
                  <div key={r.id} style={{ marginBottom: 8 }}>
                    <Space>
                      <Tag color="gold">{r.candidate_id}</Tag>
                      <Text>{r.description}</Text>
                      <Tag>{r.review_status}</Tag>
                      <Text type="secondary">{(r.confidence * 100).toFixed(0)}%</Text>
                    </Space>
                  </div>
                ))}
              </Card>
            )}

            {/* Dedup info */}
            {detail.dedup_info && (
              <Card size="small" title={
                <Space>
                  <WarningOutlined style={{ color: detail.dedup_info.is_duplicate ? '#ff4d4f' : '#52c41a' }} />
                  <span>去重检查 ({detail.dedup_info.method || '未检测到'})</span>
                </Space>
              }>
                {detail.dedup_info.duplicates.length > 0 && (
                  <div>
                    <Text type="danger" strong>发现 {detail.dedup_info.duplicates.length} 条强匹配重复</Text>
                    {detail.dedup_info.duplicates.map((d: { id: number; title: string; source_url?: string; decision_date?: string | null; review_status: string }) => (
                      <div key={d.id} style={{ marginTop: 4 }}>
                        <Tag color="red">ID: {d.id}</Tag>
                        <Text>{d.title}</Text>
                        {d.decision_date && <Text type="secondary"> · {d.decision_date}</Text>}
                      </div>
                    ))}
                  </div>
                )}
                {detail.dedup_info.candidates.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <Text type="warning" strong>发现 {detail.dedup_info.candidates.length} 条候选重复（需人工判断）</Text>
                    {detail.dedup_info.candidates.map((c: { id: number; title: string; title_similarity: number; content_similarity: number }) => (
                      <div key={c.id} style={{ marginTop: 4 }}>
                        <Tag color="orange">ID: {c.id}</Tag>
                        <Text>{c.title}</Text>
                        <Space size={4}>
                          <Tag>标题相似度: {(c.title_similarity * 100).toFixed(0)}%</Tag>
                          <Tag>内容相似度: {(c.content_similarity * 100).toFixed(0)}%</Tag>
                        </Space>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            )}
          </Space>
        ) : null}
      </Drawer>

      {/* Review reason Modal */}
      <Modal
        title={
          reviewSingleId
            ? `确认操作: ${ACTIONS_MAP[reviewSingleAction]?.label || reviewSingleAction}`
            : `批量操作: ${ACTIONS_MAP[batchAction]?.label || batchAction}`
        }
        open={reviewModalOpen}
        onOk={reviewSingleId ? doSingleReview : doBatchReview}
        onCancel={() => { setReviewModalOpen(false); setReviewSingleId(null); setReviewSingleAction(''); setBatchAction(''); }}
        okText="确认"
        cancelText="取消"
        okButtonProps={{
          danger: ['reject', 'unpublish'].includes(reviewSingleAction || batchAction),
        }}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Text>
            {reviewSingleId
              ? `将对案例 #${reviewSingleId} 执行 ${reviewSingleAction} 操作`
              : `将对 ${selectedRowKeys.length} 条案例执行 ${batchAction} 操作`}
          </Text>
          <Input.TextArea
            placeholder="审核理由（可选）"
            value={reviewReason}
            onChange={e => setReviewReason(e.target.value)}
            rows={3}
          />
        </Space>
      </Modal>

      {/* Dedup modal */}
      <Modal
        title="去重检查结果"
        open={dedupModal}
        onCancel={() => setDedupModal(false)}
        footer={null}
        width={500}
      >
        {dedupResult ? (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text strong>
              匹配方法: {dedupResult.method as string || '无'}
              {dedupResult.auto_resolved ? <Tag color="green" style={{ marginLeft: 8 }}>已自动标记</Tag> : null}
            </Text>
            {(dedupResult.duplicates as Array<Record<string, unknown>>)?.length > 0 && (
              <div>
                <Text type="danger">强匹配重复:</Text>
                {(dedupResult.duplicates as Array<Record<string, unknown>>).map((d: Record<string, unknown>, i: number) => (
                  <div key={i}><Tag color="red">ID: {d.id as number}</Tag> {d.title as string}</div>
                ))}
              </div>
            )}
            {(dedupResult.candidates as Array<Record<string, unknown>>)?.length > 0 && (
              <div>
                <Text type="warning">候选重复（需人工判断）:</Text>
                {(dedupResult.candidates as Array<Record<string, unknown>>).map((c: Record<string, unknown>, i: number) => (
                  <div key={i}><Tag color="orange">ID: {c.id as number}</Tag> {c.title as string}</div>
                ))}
              </div>
            )}
            {!(dedupResult.duplicates as Array<Record<string, unknown>>)?.length && !(dedupResult.candidates as Array<Record<string, unknown>>)?.length && (
              <Text type="success">未发现重复案例</Text>
            )}
          </Space>
        ) : (
          <Text>加载中...</Text>
        )}
      </Modal>
    </div>
  );
};

export default AdminCaseReviewTab;
