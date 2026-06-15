/**
 * DashboardTab — 系统看板 Tab 视图
 *
 * 从 AdminRules.tsx 拆分到 features/rules/components。
 */

import React from 'react';
import { Card, Row, Col, Typography, Spin, Empty, Statistic, Descriptions, Progress, Tag } from 'antd';
import { useDashboardTab } from '../hooks';

const { Text } = Typography;

const DashboardTab: React.FC = () => {
  const { stats, loading } = useDashboardTab();

  if (loading) return <Spin style={{ display: 'block', textAlign: 'center', padding: 40 }} />;
  if (!stats) return <Empty description="无法加载统计数据" />;

  const { rules, llm, risk_distribution, industries } = stats;
  const totalByType = Object.values(rules.by_type).reduce((a, b) => a + b, 0);

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}><Card><Statistic title="规则总数" value={totalByType} suffix="条" /></Card></Col>
        <Col xs={24} sm={12} lg={6}><Card><Statistic title="LLM 调用" value={llm.total_calls} suffix="次" /></Card></Col>
        <Col xs={24} sm={12} lg={6}><Card><Statistic title="Token 消耗" value={llm.total_tokens} /></Card></Col>
        <Col xs={24} sm={12} lg={6}><Card><Statistic title="成功率" value={llm.success_rate} suffix="%" precision={1} /></Card></Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} sm={12}>
          <Card title="规则类型分布" size="small">
            <Descriptions column={1} size="small">
              <Descriptions.Item label="章节完整性"><Progress percent={Math.round(rules.chapter_required / totalByType * 100)} size="small" /><Text style={{ marginLeft: 8 }}>{rules.chapter_required} 条</Text></Descriptions.Item>
              <Descriptions.Item label="关键字合规"><Progress percent={Math.round(rules.keyword_required / totalByType * 100)} size="small" /><Text style={{ marginLeft: 8 }}>{rules.keyword_required} 条</Text></Descriptions.Item>
              <Descriptions.Item label="禁用词"><Progress percent={Math.round(rules.forbidden / totalByType * 100)} size="small" /><Text style={{ marginLeft: 8 }}>{rules.forbidden} 条</Text></Descriptions.Item>
              <Descriptions.Item label="格式要求"><Progress percent={Math.round(rules.format_required / totalByType * 100)} size="small" /><Text style={{ marginLeft: 8 }}>{rules.format_required} 条</Text></Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col xs={24} sm={12}>
          <Card title="风险等级分布" size="small">
            <Descriptions column={1} size="small">
              <Descriptions.Item label="高风险"><Progress percent={Math.round(risk_distribution.high / totalByType * 100)} strokeColor="#dc2626" size="small" /><Text style={{ marginLeft: 8 }}>{risk_distribution.high} 条</Text></Descriptions.Item>
              <Descriptions.Item label="中风险"><Progress percent={Math.round(risk_distribution.medium / totalByType * 100)} strokeColor="#eab308" size="small" /><Text style={{ marginLeft: 8 }}>{risk_distribution.medium} 条</Text></Descriptions.Item>
              <Descriptions.Item label="低风险"><Progress percent={Math.round(risk_distribution.low / totalByType * 100)} strokeColor="#16a34a" size="small" /><Text style={{ marginLeft: 8 }}>{risk_distribution.low} 条</Text></Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} sm={12}>
          <Card title="可用行业" size="small">
            {industries.length > 0 ? industries.map(ind => <Tag key={ind} style={{ marginBottom: 4 }}>{ind}</Tag>) : <Text type="secondary">无</Text>}
          </Card>
        </Col>
        <Col xs={24} sm={12}>
          <Card title="最近 LLM 调用" size="small">
            {llm.recent_calls.length > 0 ? (
              <div>
                {llm.recent_calls.slice(0, 5).map((c, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #f0f0f0' }}>
                    <span><Tag color={c.success ? 'green' : 'red'}>{c.model}</Tag></span>
                    <Text type="secondary" style={{ fontSize: 12 }}>{c.tokens}t · {c.duration}s</Text>
                  </div>
                ))}
              </div>
            ) : <Text type="secondary">暂无调用记录</Text>}
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default DashboardTab;
