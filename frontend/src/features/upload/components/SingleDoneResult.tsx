/**
 * SingleDoneResult — 单文件完成结果页
 *
 * 从 Upload.tsx 拆分。
 */

import React from 'react';
import { Card, Typography, Button, Result, Tag } from 'antd';
import { ArrowRightOutlined, ThunderboltOutlined, SafetyOutlined, FlagOutlined, ExperimentOutlined, MergeCellsOutlined } from '@ant-design/icons';
import type { PipelineResult } from '../types';

const { Text } = Typography;

interface SingleDoneResultProps {
  score: number;
  reportId: number;
  pipeline?: PipelineResult;
  onViewReport: (id: number) => void;
  onReset: () => void;
}

const SingleDoneResult: React.FC<SingleDoneResultProps> = ({ score, reportId, pipeline, onViewReport, onReset }) => (
  <Result status="success" title="合规检查完成" subTitle="系统已完成对招标文件的全部合规审查"
    extra={[
      pipeline && (
        <Card key="pipeline" size="small" style={{ marginBottom: 16, borderRadius: 10, border: '1px solid var(--color-border)', textAlign: 'left', maxWidth: 480, margin: '0 auto 16px auto' }} styles={{ body: { padding: '14px 18px' } }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[
              { icon: <ThunderboltOutlined />, label: '智能路由', val: pipeline.traffic_light === 'green' ? '🟢 绿灯 · 跳过AI' : '🔴 红灯 · 进入AI审查' },
              { icon: <SafetyOutlined />, label: '规则引擎', val: `命中${score < 85 ? '违规' : '0'}项` },
              { icon: <FlagOutlined />, label: '参数倾向性', val: `发现${pipeline.parameter_bias_findings}个风险 · 得分${pipeline.parameter_bias_score}` },
              { icon: <ExperimentOutlined />, label: 'AI语义', val: pipeline.traffic_light === 'green' ? '已跳过' : '分析完成' },
              { icon: <MergeCellsOutlined />, label: '风险合并', val: `${pipeline.merge_risk_level} · ${pipeline.merge_review_status}${pipeline.merge_requires_human_review ? ' · 需人工复核' : ' · 自动通过'}` },
            ].map((row, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: 'var(--color-action)', fontSize: 14 }}>{row.icon}</span>
                <Text style={{ fontSize: 13 }}>{row.label}</Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 'auto' }}>{row.val}</Text>
              </div>
            ))}
          </div>
        </Card>
      ),
      <div key="score" style={{ marginBottom: 16 }}>
        <Tag color={score >= 85 ? 'green' : score >= 60 ? 'gold' : 'red'} style={{ padding: '4px 16px', borderRadius: 20, fontSize: 16 }}>合规评分：{score}</Tag>
      </div>,
      <Button key="report" type="primary" size="large" icon={<ArrowRightOutlined />} onClick={() => onViewReport(reportId)} style={{ borderRadius: 8, paddingLeft: 28, paddingRight: 28 }}>查看详细报告</Button>,
      <Button key="new" onClick={onReset} style={{ borderRadius: 8 }}>检查新文件</Button>,
    ]} />
);

export default SingleDoneResult;
