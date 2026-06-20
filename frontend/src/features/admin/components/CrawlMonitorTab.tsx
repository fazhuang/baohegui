/**
 * CrawlMonitorTab — 采集监控面板
 *
 * Phase 2 Block E: 管理后台采集监控 Tab
 * - 最近任务状态和触发类型
 * - 四个来源的 fetched/saved/duplicates 明细
 * - 连续失败次数、最近成功时间、健康状态
 * - 管理员可见的简要错误摘要
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  Card, Col, Descriptions, Row, Statistic, Table, Tag, Typography,
  Spin, Empty, Collapse, Alert, Space,
} from 'antd';
import {
  ReloadOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ExclamationCircleOutlined, ClockCircleOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import http from '../../../services/http';

const { Text } = Typography;

interface CrawlJobItemSummary {
  source_name: string;
  source_type: string;
  status: string;
  fetched_count: number;
  saved_count: number;
  duplicate_count: number;
  error_type?: string;
  error_message?: string;
  duration_ms?: number;
  started_at?: string;
  finished_at?: string;
}

interface CrawlJobSummary {
  id: number;
  job_type: string;
  status: string;
  trigger_type: string;
  started_at: string | null;
  finished_at: string | null;
  retry_count: number;
  total_sources: number;
  successful_sources: number;
  failed_sources: number;
  total_fetched: number;
  total_saved: number;
  total_duplicates: number;
  kg_synced: number;
  error_message?: string;
  items: CrawlJobItemSummary[];
  created_at: string | null;
}

interface CrawlStatusData {
  running: boolean;
  case_scrape_enabled: boolean;
  case_scrape_interval_hours: number;
  last_case_scrape: {
    id: number;
    status: string;
    trigger_type: string;
    started_at: string | null;
    finished_at: string | null;
    total_saved: number;
    total_fetched: number;
    total_duplicates: number;
    kg_synced: number;
    per_source: Record<string, {
      status: string;
      saved: number;
      fetched: number;
      duplicates: number;
      duration_ms?: number;
    }>;
  } | null;
  health: Record<string, string>;
}

const STATUS_TAG_MAP: Record<string, { color: string; icon: React.ReactNode }> = {
  success: { color: 'green', icon: <CheckCircleOutlined /> },
  partial: { color: 'orange', icon: <ExclamationCircleOutlined /> },
  failed: { color: 'red', icon: <CloseCircleOutlined /> },
  running: { color: 'blue', icon: <SyncOutlined spin /> },
  skipped: { color: 'default', icon: <ClockCircleOutlined /> },
};

const SOURCE_LABELS: Record<string, string> = {
  ccgp: 'CCGP 全国',
  ningxia: '宁夏政府采购网',
  shaanxi: '陕西政府采购网',
  mof: '财政部国库司',
};

async function fetchStatus(): Promise<CrawlStatusData> {
  const { data } = await http.get('/crawler/status');
  return data;
}

async function fetchJobs(limit: number = 5): Promise<{ jobs: CrawlJobSummary[] }> {
  const { data } = await http.get('/crawler/jobs', { params: { limit } });
  return data;
}

const CrawlMonitorTab: React.FC = () => {
  const [status, setStatus] = useState<CrawlStatusData | null>(null);
  const [jobs, setJobs] = useState<CrawlJobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, j] = await Promise.all([fetchStatus(), fetchJobs(5)]);
      setStatus(s);
      setJobs(j.jobs);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const lastScrape = status?.last_case_scrape;

  const healthStatus = lastScrape
    ? (lastScrape.status === 'failed' ? 'degraded' : lastScrape.status)
    : 'collecting';

  const healthLabel: Record<string, string> = {
    success: '正常',
    partial: '部分成功',
    failed: '异常',
    degraded: '降级',
    collecting: '数据收集中',
    not_enough_data: '数据不足',
  };

  const sourceColumns = [
    { title: '来源', dataIndex: 'source_name', key: 'source_name',
      render: (v: string) => SOURCE_LABELS[v] || v },
    { title: '状态', dataIndex: 'status', key: 'status',
      render: (s: string) => {
        const cfg = STATUS_TAG_MAP[s] || STATUS_TAG_MAP.skipped;
        return <Tag color={cfg.color} icon={cfg.icon}>{s}</Tag>;
      }},
    { title: '抓取', dataIndex: 'fetched_count', key: 'fetched' },
    { title: '保存', dataIndex: 'saved_count', key: 'saved' },
    { title: '重复', dataIndex: 'duplicate_count', key: 'dups' },
    { title: '耗时(ms)', dataIndex: 'duration_ms', key: 'duration' },
  ];

  const perSourceData = lastScrape?.per_source
    ? Object.entries(lastScrape.per_source).map(([name, info]) => ({
        source_name: name,
        status: info.status,
        fetched_count: info.fetched,
        saved_count: info.saved,
        duplicate_count: info.duplicates,
        duration_ms: info.duration_ms,
      }))
    : [];

  return (
    <div style={{ padding: 16 }}>
      <Spin spinning={loading}>
        {error && (
          <Alert type="error" message={error} closable style={{ marginBottom: 16 }}
            action={<ReloadOutlined onClick={load} style={{ cursor: 'pointer' }} />}
          />
        )}

        {/* 概览卡片 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="采集状态"
                value={lastScrape
                  ? healthLabel[lastScrape.status] || lastScrape.status
                  : healthLabel.collecting}
                valueStyle={{
                  color: lastScrape?.status === 'failed' ? 'red'
                    : lastScrape?.status === 'partial' ? 'orange' : 'green',
                }}
              />
              {!lastScrape && <Text type="secondary" style={{ fontSize: 12 }}>
                尚未执行首次采集</Text>}
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="总保存" value={lastScrape?.total_saved ?? 0} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="总抓取" value={lastScrape?.total_fetched ?? 0} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="KG 同步" value={lastScrape?.kg_synced ?? 0} />
            </Card>
          </Col>
        </Row>

        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Statistic title="健康状态" value={healthLabel[healthStatus] || healthStatus}
              valueStyle={{ fontSize: 16 }} />
            {healthStatus === 'collecting' && (
              <Text type="secondary" style={{ fontSize: 11, display: 'block' }}>
                需要至少 7 天连续稳定运行数据才能显示 healthy
              </Text>
            )}
          </Col>
          <Col span={8}>
            <Statistic title="最近任务" value={lastScrape?.trigger_type ?? '-'} />
          </Col>
          <Col span={8}>
            <Statistic title="最近运行" value={lastScrape?.finished_at
              ? new Date(lastScrape.finished_at).toLocaleString() : '-'} />
          </Col>
        </Row>

        {/* 来源明细表 */}
        <Card title="最近一次采集 — 来源明细" size="small" style={{ marginBottom: 16 }}>
          {perSourceData.length > 0 ? (
            <Table
              dataSource={perSourceData}
              columns={sourceColumns}
              rowKey="source_name"
              pagination={false}
              size="small"
            />
          ) : (
            <Empty description="暂无采集数据" />
          )}
        </Card>

        {/* 最近任务历史 */}
        <Card title="最近采集任务" size="small">
          {jobs.length > 0 ? (
            <Collapse
              size="small"
              items={jobs.map((job) => ({
                key: String(job.id),
                label: (
                  <Space>
                    <Tag color={STATUS_TAG_MAP[job.status]?.color || 'default'}>
                      {job.status}
                    </Tag>
                    <Text>{job.trigger_type}</Text>
                    <Text type="secondary">
                      {job.finished_at
                        ? new Date(job.finished_at).toLocaleString()
                        : job.started_at
                          ? new Date(job.started_at).toLocaleString()
                          : '-'}
                    </Text>
                  </Space>
                ),
                children: (
                  <>
                    <Descriptions size="small" column={4}>
                      <Descriptions.Item label="保存">{job.total_saved}</Descriptions.Item>
                      <Descriptions.Item label="抓取">{job.total_fetched}</Descriptions.Item>
                      <Descriptions.Item label="重复">{job.total_duplicates}</Descriptions.Item>
                      <Descriptions.Item label="KG 同步">{job.kg_synced}</Descriptions.Item>
                      <Descriptions.Item label="成功来源">{job.successful_sources}</Descriptions.Item>
                      <Descriptions.Item label="失败来源">{job.failed_sources}</Descriptions.Item>
                      <Descriptions.Item label="重试次数">{job.retry_count}</Descriptions.Item>
                      <Descriptions.Item label="来源数">{job.total_sources}</Descriptions.Item>
                    </Descriptions>
                    {job.error_message && (
                      <Alert type="error" message={job.error_message} style={{ marginTop: 8, fontSize: 12 }} />
                    )}
                    {job.items.length > 0 && (
                      <Table
                        dataSource={job.items}
                        columns={sourceColumns}
                        rowKey="source_name"
                        pagination={false}
                        size="small"
                        style={{ marginTop: 8 }}
                      />
                    )}
                  </>
                ),
              }))}
            />
          ) : (
            <Empty description="暂无任务记录" />
          )}
        </Card>
      </Spin>
    </div>
  );
};

export default CrawlMonitorTab;
