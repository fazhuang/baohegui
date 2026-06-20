/**
 * CandidateRulesTab — 候选规则审核
 *
 * Phase 2: 管理员审核规则矿机产出的候选规则
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button, Card, Col, Drawer, Input, Modal, Pagination, Row,
  Select, Space, Statistic, Table, Tag, Typography, message, Descriptions,
} from 'antd';
import {
  CheckOutlined, CloseOutlined, EyeOutlined, CopyOutlined,
  SearchOutlined, ReloadOutlined,
} from '@ant-design/icons';
import {
  getCandidateRules, getCandidateRuleStats, getCandidateRuleDetail,
  reviewCandidateRules,
} from '../../../services/api';
import type { CandidateRuleItem, CandidateRuleDetail } from '../../../types';

const { Text, Paragraph } = Typography;

const REVIEW_STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending: { label: '待审核', color: 'orange' },
  approved: { label: '已通过', color: 'green' },
  rejected: { label: '已拒绝', color: 'red' },
  duplicate: { label: '重复', color: 'magenta' },
};

const RISK_MAP: Record<string, { label: string; color: string }> = {
  critical: { label: '严重', color: 'red' },
  high: { label: '高', color: 'volcano' },
  medium: { label: '中', color: 'orange' },
  low: { label: '低', color: 'default' },
};

const CandidateRulesTab: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [candidates, setCandidates] = useState<CandidateRuleItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);

  // Filters
  const [statusFilter, setStatusFilter] = useState('');
  const [riskFilter, setRiskFilter] = useState('');
  const [minConfidence, setMinConfidence] = useState(0);

  // Stats
  const [stats, setStats] = useState<Record<string, number> | null>(null);

  // Detail
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detail, setDetail] = useState<CandidateRuleDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Review
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [reviewAction, setReviewAction] = useState('');
  const [reviewNote, setReviewNote] = useState('');
  const [promotedRuleId, setPromotedRuleId] = useState('');

  const loadList = useCallback(async (p: number = 1) => {
    setLoading(true);
    try {
      const res = await getCandidateRules({
        review_status: statusFilter || undefined,
        risk_level: riskFilter || undefined,
        min_confidence: minConfidence || undefined,
        limit: pageSize,
        offset: (p - 1) * pageSize,
      });
      setCandidates(res.candidates);
      setTotal(res.total);
      setPage(p);
    } catch {
      // handled by interceptor
    } finally {
      setLoading(false);
    }
  }, [statusFilter, riskFilter, minConfidence, pageSize]);

  const loadStats = useCallback(async () => {
    try {
      const res = await getCandidateRuleStats();
      setStats(res.by_status);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadList(1);
    loadStats();
  }, []); // eslint-disable-line

  const openDetail = useCallback(async (id: number) => {
    setDrawerOpen(true);
    setDetailLoading(true);
    try {
      const d = await getCandidateRuleDetail(id);
      setDetail(d);
    } catch {
      // handled
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const doReview = useCallback(async () => {
    if (selectedRowKeys.length === 0) return;
    try {
      const res = await reviewCandidateRules({
        candidate_ids: selectedRowKeys.map(Number),
        action: reviewAction,
        note: reviewNote,
        promoted_rule_id: reviewAction === 'approve' && promotedRuleId ? promotedRuleId : undefined,
      });
      message.success(`操作完成: 成功 ${res.success_count}, 失败 ${res.error_count}`);
      if (res.errors.length > 0) {
        message.warning(res.errors.map((e: Record<string, unknown>) => e.error).join('; '));
      }
      setSelectedRowKeys([]);
      setReviewModalOpen(false);
      setReviewNote('');
      setPromotedRuleId('');
      loadList(page);
      loadStats();
    } catch {
      message.error('操作失败');
    }
  }, [selectedRowKeys, reviewAction, reviewNote, promotedRuleId, page, loadList, loadStats]);

  const columns = useMemo(() => [
    {
      title: 'ID',
      dataIndex: 'candidate_id',
      width: 140,
    },
    {
      title: '描述',
      dataIndex: 'description',
      ellipsis: true,
      width: 260,
    },
    {
      title: '审核状态',
      dataIndex: 'review_status',
      width: 90,
      render: (s: string) => {
        const info = REVIEW_STATUS_MAP[s] || { label: s, color: 'default' };
        return <Tag color={info.color}>{info.label}</Tag>;
      },
    },
    {
      title: '风险等级',
      dataIndex: 'risk_level',
      width: 80,
      render: (r: string) => {
        const info = RISK_MAP[r] || { label: r, color: 'default' };
        return <Tag color={info.color}>{info.label}</Tag>;
      },
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      width: 80,
      render: (c: number) => (c * 100).toFixed(0) + '%',
    },
    {
      title: '来源',
      dataIndex: 'source_type',
      width: 70,
    },
    {
      title: '已升级',
      dataIndex: 'promoted_to',
      width: 100,
      render: (p: string) => p ? <Tag color="blue">{p}</Tag> : null,
    },
    {
      title: '操作',
      width: 150,
      fixed: 'right' as const,
      render: (_: unknown, r: CandidateRuleItem) => (
        <Space size={4}>
          <Button size="small" icon={<EyeOutlined />} onClick={() => openDetail(r.id)}>详情</Button>
          {r.review_status === 'pending' && (
            <>
              <Button size="small" type="primary" icon={<CheckOutlined />}
                onClick={() => {
                  setSelectedRowKeys([r.id]);
                  setReviewAction('approve');
                  setReviewNote('');
                  setPromotedRuleId('');
                  setReviewModalOpen(true);
                }}>
                通过
              </Button>
              <Button size="small" danger icon={<CloseOutlined />}
                onClick={() => {
                  setSelectedRowKeys([r.id]);
                  setReviewAction('reject');
                  setReviewNote('');
                  setReviewModalOpen(true);
                }}>
                拒绝
              </Button>
            </>
          )}
        </Space>
      ),
    },
  ], [openDetail]);

  const rowSelection = {
    selectedRowKeys,
    onChange: (keys: React.Key[]) => setSelectedRowKeys(keys),
  };

  return (
    <div>
      {/* Stats */}
      {stats && (
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={12} sm={6}><Card size="small"><Statistic title="待审核" value={stats.pending ?? 0} valueStyle={{ color: '#fa8c16' }} /></Card></Col>
          <Col xs={12} sm={6}><Card size="small"><Statistic title="已通过" value={stats.approved ?? 0} valueStyle={{ color: '#52c41a' }} /></Card></Col>
          <Col xs={12} sm={6}><Card size="small"><Statistic title="已拒绝" value={stats.rejected ?? 0} valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
          <Col xs={12} sm={6}><Card size="small"><Statistic title="重复" value={stats.duplicate ?? 0} valueStyle={{ color: '#eb2f96' }} /></Card></Col>
        </Row>
      )}

      {/* Filters */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} align="middle">
          <Col xs={12} sm={3}>
            <Select
              value={statusFilter}
              onChange={v => setStatusFilter(v)}
              style={{ width: '100%' }}
              placeholder="审核状态"
              allowClear
              options={[
                { label: '待审核', value: 'pending' },
                { label: '已通过', value: 'approved' },
                { label: '已拒绝', value: 'rejected' },
                { label: '重复', value: 'duplicate' },
              ]}
            />
          </Col>
          <Col xs={12} sm={3}>
            <Select
              value={riskFilter}
              onChange={v => setRiskFilter(v)}
              style={{ width: '100%' }}
              placeholder="风险等级"
              allowClear
              options={[
                { label: '严重', value: 'critical' },
                { label: '高', value: 'high' },
                { label: '中', value: 'medium' },
                { label: '低', value: 'low' },
              ]}
            />
          </Col>
          <Col xs={12} sm={3}>
            <Select
              value={minConfidence}
              onChange={v => setMinConfidence(v)}
              style={{ width: '100%' }}
              placeholder="最低置信度"
              options={[
                { label: '全部', value: 0 },
                { label: '≥ 30%', value: 0.3 },
                { label: '≥ 50%', value: 0.5 },
                { label: '≥ 70%', value: 0.7 },
              ]}
            />
          </Col>
          <Col xs={12} sm={5}>
            <Button type="primary" icon={<SearchOutlined />} onClick={() => loadList(1)} loading={loading}>查询</Button>
            <Button style={{ marginLeft: 8 }} icon={<ReloadOutlined />} onClick={() => loadList(page)} />
          </Col>
          <Col xs={24} sm={10} style={{ textAlign: 'right' }}>
            {selectedRowKeys.length > 0 && (
              <Space>
                <Text>{selectedRowKeys.length} 条已选</Text>
                <Button type="primary" icon={<CheckOutlined />} onClick={() => { setReviewAction('approve'); setReviewModalOpen(true); }}>
                  批量通过
                </Button>
                <Button danger icon={<CloseOutlined />} onClick={() => { setReviewAction('reject'); setReviewModalOpen(true); }}>
                  批量拒绝
                </Button>
                <Button icon={<CopyOutlined />} onClick={() => { setReviewAction('mark_duplicate'); setReviewModalOpen(true); }}>
                  标记重复
                </Button>
              </Space>
            )}
          </Col>
        </Row>
      </Card>

      {/* Table */}
      <Card size="small" title={`候选规则 (${total} 条)`}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={candidates}
          loading={loading}
          size="small"
          scroll={{ x: 1000 }}
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
            onChange={p => loadList(p)}
            showSizeChanger={false}
            showTotal={t => `共 ${t} 条`}
          />
        </div>
      </Card>

      {/* Detail Drawer */}
      <Drawer
        title={`候选规则: ${detail?.candidate_id as string || ''}`}
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setDetail(null); }}
        width={560}
      >
        {detailLoading ? (
          <div style={{ textAlign: 'center', padding: 64 }}>加载中...</div>
        ) : detail ? (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Card size="small" title="基本信息">
              <Descriptions column={1} size="small">
                <Descriptions.Item label="候选ID">{detail.candidate_id as string}</Descriptions.Item>
                <Descriptions.Item label="规则类型">{detail.rule_type as string}</Descriptions.Item>
                <Descriptions.Item label="检测目标">{detail.target as string}</Descriptions.Item>
                <Descriptions.Item label="描述">{detail.description as string}</Descriptions.Item>
                <Descriptions.Item label="风险等级">
                  <Tag color={RISK_MAP[detail.risk_level as string]?.color}>
                    {RISK_MAP[detail.risk_level as string]?.label || detail.risk_level as string}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="匹配模式">
                  <Text code>{detail.pattern as string || '-'}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="法规依据">{detail.law_ref as string || '-'}</Descriptions.Item>
                <Descriptions.Item label="整改建议">{detail.suggestion as string || '-'}</Descriptions.Item>
                <Descriptions.Item label="置信度">
                  {((detail.confidence as number) * 100)?.toFixed(0)}%
                </Descriptions.Item>
                <Descriptions.Item label="审核状态">
                  <Tag color={REVIEW_STATUS_MAP[detail.review_status as string]?.color}>
                    {REVIEW_STATUS_MAP[detail.review_status as string]?.label}
                  </Tag>
                </Descriptions.Item>
                {detail.review_note && (
                  <Descriptions.Item label="审核意见">{detail.review_note as string}</Descriptions.Item>
                )}
                {detail.promoted_to && (
                  <Descriptions.Item label="已升级为">
                    <Tag color="blue">{detail.promoted_to as string}</Tag>
                  </Descriptions.Item>
                )}
              </Descriptions>
            </Card>

            {/* Evidence */}
            {detail.evidence && (
              <Card size="small" title="证据片段">
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="源案例">{detail.source_case?.title || detail.evidence.case_id || '-'}</Descriptions.Item>
                  <Descriptions.Item label="匹配片段">
                    {(detail.evidence.matches || []).map((m: string, i: number) => (
                      <Paragraph key={i} style={{ background: '#f5f5f5', padding: 8, borderRadius: 4, marginBottom: 4, whiteSpace: 'pre-wrap' }}>
                        {m}
                      </Paragraph>
                    ))}
                  </Descriptions.Item>
                </Descriptions>
              </Card>
            )}

            {/* Source case */}
            {detail.source_case && (
              <Card size="small" title="来源案例">
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="标题">{detail.source_case.title}</Descriptions.Item>
                  <Descriptions.Item label="决定类型">{detail.source_case.decision_type}</Descriptions.Item>
                  <Descriptions.Item label="省份">{detail.source_case.province}</Descriptions.Item>
                </Descriptions>
              </Card>
            )}
          </Space>
        ) : null}
      </Drawer>

      {/* Review Modal */}
      <Modal
        title={`确认${reviewAction === 'approve' ? '通过' : reviewAction === 'reject' ? '拒绝' : '标记重复'}`}
        open={reviewModalOpen}
        onOk={doReview}
        onCancel={() => { setReviewModalOpen(false); setReviewAction(''); setPromotedRuleId(''); }}
        okText="确认"
        cancelText="取消"
        okButtonProps={{ danger: reviewAction !== 'approve' }}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Text>将对 {selectedRowKeys.length} 条候选规则执行 {reviewAction} 操作</Text>
          {reviewAction === 'approve' && (
            <Input
              placeholder="升级为正式规则 ID（可选，如 R999）"
              value={promotedRuleId}
              onChange={e => setPromotedRuleId(e.target.value)}
            />
          )}
          <Input.TextArea
            placeholder="审核意见（可选）"
            value={reviewNote}
            onChange={e => setReviewNote(e.target.value)}
            rows={2}
          />
        </Space>
      </Modal>
    </div>
  );
};

export default CandidateRulesTab;
