/**
 * StepGuide — 分步骤使用指南面板
 *
 * 从 Upload.tsx 拆分。
 */

import React from 'react';
import { Alert, Collapse } from 'antd';

const GUIDE_STEPS = [
  { step: 1, title: '上传文件', desc: '拖拽或选择 PDF/Word 文件，系统自动上传' },
  { step: 2, title: '文档解析', desc: '自动提取招标文件的章节结构' },
  { step: 3, title: '五层审查', desc: '智能路由→规则引擎→参数倾向→AI语义→风险合并' },
  { step: 4, title: '查看报告', desc: '获得合规评分和详细整改建议' },
];

const StepGuide: React.FC = () => (
  <Collapse ghost size="small" items={[{
    key: 'guide', label: <span style={{ color: 'var(--color-action)', fontSize: 13 }}>首次使用？查看操作指南</span>,
    children: (
      <div>
        <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap', marginBottom: 8 }}>
          {GUIDE_STEPS.map(({ step, title, desc }) => (
            <div key={step} style={{ flex: '1 0 140px', minWidth: 120 }}>
              <div className="guide-step-icon">{step}</div>
              <div style={{ fontWeight: 600, fontSize: 13, marginTop: 6 }}>{title}</div>
              <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 2 }}>{desc}</div>
            </div>
          ))}
        </div>
        <Alert message="合规检查通常需要 1-3 分钟，具体时间取决于文件大小和复杂程度" type="info" showIcon={false}
          style={{ background: 'var(--color-brand-light)', border: 'none', fontSize: 12, padding: '8px 12px', borderRadius: 6 }} />
      </div>
    ),
  }]} style={{ marginBottom: 16 }} />
);

export default StepGuide;
