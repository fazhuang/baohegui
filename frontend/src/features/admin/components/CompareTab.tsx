/**
 * CompareTab — 文件差异对比 Tab 组件
 *
 * 从 AdminPanel.tsx 拆分。
 */

import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Card, Row, Col, Typography, Select, Button, message, Empty,
  Descriptions, Statistic, Progress, Alert, Tag,
} from 'antd';
import { SwapOutlined } from '@ant-design/icons';
import { compareFiles, listReports } from '../../../services/api';
import type { CompareResult } from '../../../types/admin-types';
import { getErrorMessage } from '../../../utils/error';

const { Title, Text } = Typography;

interface ReportItem {
  id: number;
  file_id: number;
  filename?: string;
  total_score: number;
  created_at: string;
}

const CompareTab: React.FC = () => {
  const [cmpSearchParams] = useSearchParams();
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [selectedA, setSelectedA] = useState<number | null>(null);
  const [selectedB, setSelectedB] = useState<number | null>(null);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    listReports().then((data: { items: ReportItem[] }) => {
      setReports(data.items);
      const initialA = cmpSearchParams.get('a');
      const initialB = cmpSearchParams.get('b');
      if (initialA) setSelectedA(Number(initialA));
      if (initialB) setSelectedB(Number(initialB));
    }).catch(() => {});
  }, [cmpSearchParams]);

  const handleCompare = async () => {
    if (!selectedA || !selectedB) return;
    setLoading(true);
    try { setResult(await compareFiles(selectedA, selectedB)); }
    catch (e: unknown) { message.error(getErrorMessage(e, '对比失败')); }
    finally { setLoading(false); }
  };

  const fileOptions = reports.map(r => ({
    value: r.file_id,
    label: `#${r.file_id} — 评分 ${r.total_score} (${r.created_at?.slice(0, 10) || '?'})`,
  }));

  return (
    <div>
      <Title level={4}><SwapOutlined /> 文件差异对比</Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>选择两个已检查的文件，对比其章节结构差异和合规评分变化</Text>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={10}><Select placeholder="选择文件 A" options={fileOptions} value={selectedA} onChange={setSelectedA}
          style={{ width: '100%' }} showSearch filterOption={(input, option) => (option?.label as string || '').includes(input)} /></Col>
        <Col span={4} style={{ textAlign: 'center', paddingTop: 4 }}><SwapOutlined style={{ fontSize: 20, color: '#999' }} /></Col>
        <Col span={10}><Select placeholder="选择文件 B" options={fileOptions} value={selectedB} onChange={setSelectedB}
          style={{ width: '100%' }} showSearch filterOption={(input, option) => (option?.label as string || '').includes(input)} /></Col>
      </Row>
      <Button type="primary" icon={<SwapOutlined />} onClick={handleCompare} loading={loading}
        disabled={!selectedA || !selectedB} block style={{ marginBottom: 20, borderRadius: 8 }}>开始对比</Button>
      {result && (
        <>
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
            {result.info.is_same_file && <Alert message="检测到同一文件（SHA-256 哈希一致）" type="info" showIcon style={{ marginTop: 12, borderRadius: 6 }} />}
          </Card>
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
          {result.score_diff && (
            <Card size="small" title="合规评分变化">
              <Row gutter={[16, 12]}>
                {Object.entries(result.score_diff).map(([key, val]) => {
                  const scoreItem = val as { a: number; b: number; delta?: number };
                  const delta = scoreItem.delta ?? 0;
                  const color = delta > 0 ? '#16a34a' : delta < 0 ? '#dc2626' : '#6b7280';
                  return (
                    <Col span={12} key={key}>
                      <Statistic title={key} value={scoreItem.b}
                        suffix={delta !== 0 ? <Text style={{ color, fontSize: 14 }}>({delta > 0 ? '+' : ''}{delta})</Text> : undefined}
                        valueStyle={{ fontSize: 20 }} />
                      <Progress percent={scoreItem.b} size="small" strokeColor={scoreItem.b >= 60 ? '#16a34a' : '#eab308'} />
                    </Col>
                  );
                })}
              </Row>
            </Card>
          )}
        </>
      )}
    </div>
  );
};

export default CompareTab;
