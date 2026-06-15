/**
 * UploadPage — 文件上传与五层审查
 *
 * 编排层：使用 features/upload 的队列状态和组件。
 */

import React, { useState, useRef } from 'react';
import {
  Card, Typography, Button, Alert, Space, Tag,
  Result, Collapse, Tour,
} from 'antd';
import {
  InboxOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ArrowRightOutlined, ThunderboltOutlined, SafetyOutlined,
  FlagOutlined, ExperimentOutlined, MergeCellsOutlined,
  FileOutlined, LoadingOutlined, HistoryOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { listReports } from '../services/api';
import type { ReportListItem } from '../types';
import { useUploadQueue } from '../features/upload/hooks/useUploadQueue';
import { ProcessNode } from '../features/upload/components';
import { STEPS, MAX_BATCH, type FileItemData } from '../features/upload/types';

const { Title, Text } = Typography;

// ── 最近检查概览 ────────────────────────────────────────────

const RecentCheckStrip: React.FC<{ onClick?: (id: number) => void }> = ({ onClick }) => {
  const [items, setItems] = useState<ReportListItem[]>([]);
  const [loaded, setLoaded] = useState(false);

  React.useEffect(() => {
    listReports()
      .then(reports => setItems(reports.items.slice(0, 5)))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  if (!loaded || items.length === 0) return null;

  const scoreColor = (score: number) =>
    score >= 85 ? 'var(--color-success)' : score >= 60 ? 'var(--color-warning)' : 'var(--color-error)';

  return (
    <div style={{ marginBottom: 16 }}>
      <div className="section-header">
        <HistoryOutlined style={{ fontSize: 14, color: 'var(--color-text-tertiary)' }} />
        <Text style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>最近检查</Text>
      </div>
      <div className="recent-check-strip">
        {items.map((item) => (
          <div key={item.id} className="recent-check-item" onClick={() => onClick?.(item.id)}>
            <Text style={{ fontSize: 12, color: 'var(--color-text)', display: 'block' }} ellipsis>
              {item.file_id || `报告 #${item.id}`}
            </Text>
            <div className="recent-check-score" style={{
              width: `${Math.max(item.total_score || 0, 5)}%`,
              backgroundColor: scoreColor(item.total_score || 0),
            }} />
          </div>
        ))}
      </div>
    </div>
  );
};

// ── 文件状态图标 ────────────────────────────────────────────

const FileStatusIcon: React.FC<{ status: FileItemData['status'] }> = ({ status }) => {
  switch (status) {
    case 'pending': return <FileOutlined style={{ color: 'var(--color-text-tertiary)' }} />;
    case 'uploading': case 'checking': return <LoadingOutlined style={{ color: 'var(--color-action)' }} />;
    case 'done': return <CheckCircleOutlined style={{ color: 'var(--color-success)' }} />;
    case 'error': return <CloseCircleOutlined style={{ color: 'var(--color-error)' }} />;
  }
};

const STATUS_LABELS: Record<FileItemData['status'], string> = {
  pending: '等待中', uploading: '上传中', checking: '检查中', done: '已完成', error: '失败',
};

// ═══════════════════════════════════════════════════════════════
// 主页面
// ═══════════════════════════════════════════════════════════════

const UploadPage: React.FC = () => {
  const navigate = useNavigate();
  const queue = useUploadQueue();
  const { files, currentStep, error, result, progress, isRunning, isBatchMode, doneCount,
    processingRef, fileRef, addFiles, handleRetryFile, handleRetryAll, resetAll, setError, getStepStatus } = queue;

  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [tourOpen, setTourOpen] = useState(false);

  const validateFiles = (fileList: File[]): File[] => {
    const valid: File[] = [];
    for (const file of fileList.slice(0, MAX_BATCH)) {
      const ext = file.name.split('.').pop()?.toLowerCase();
      if (!['pdf', 'docx'].includes(ext || '')) {
        setError({ step: 'idle', message: `"${file.name}" 格式不支持，仅支持 PDF 和 Word (.docx)` });
        return [];
      }
      if (file.size > 50 * 1024 * 1024) {
        setError({ step: 'idle', message: `"${file.name}" 超过 50MB 大小限制` });
        return [];
      }
      valid.push(file);
    }
    return valid;
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragOver(false);
    if (isRunning || processingRef.current) return;
    const dropped = Array.from(e.dataTransfer.files);
    const valid = validateFiles(dropped);
    if (valid.length > 0) addFiles(valid);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files;
    if (!selected || selected.length === 0 || isRunning || processingRef.current) return;
    const valid = validateFiles(Array.from(selected));
    e.target.value = '';
    if (valid.length > 0) addFiles(valid);
  };

  const tourSteps = [
    { title: '包合规操作指南', description: '帮助您在提交前发现合规问题。只需三步。', target: () => document.getElementById('tour-upload-area') as HTMLElement, placement: 'bottom' as const },
    { title: '上传文件', description: '拖拽招标文件到上传区域。支持 PDF 和 Word。', target: () => document.getElementById('tour-upload-area') as HTMLElement, placement: 'bottom' as const },
    { title: '查看操作指南', description: '点击此处查看详细的操作说明。', target: () => document.querySelector('.ant-collapse-header') as HTMLElement, placement: 'right' as const },
    { title: '等待检查', description: '自动完成上传→解析→五层审查流水线', target: () => document.getElementById('process-track') as HTMLElement, placement: 'top' as const },
  ];

  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <style>{`
@media (max-width: 767px) {
  .upload-zone { padding: 24px 16px; min-height: 160px; }
  .process-track { flex-direction: column; align-items: flex-start; gap: 12px; }
  .process-line { display: none; }
  .process-node { flex-direction: row; align-items: center; gap: 12px; min-width: auto; }
  .process-node-circle { width: 32px; height: 32px; font-size: 14px; }
  .recent-check-strip { flex-wrap: wrap; }
}
`}</style>
      <Title level={3} style={{ fontSize: 20, fontWeight: 600, marginBottom: 4 }}>上传招标文件</Title>
      <Text type="secondary" style={{ marginBottom: 20, display: 'block', fontSize: 14 }}>
        支持 PDF 和 Word 格式，单文件不超过 50MB，最多 {MAX_BATCH} 份文件
      </Text>

      {/* 最近检查 + 使用指南 */}
      {currentStep === 'idle' && files.length === 0 && (
        <>
          <RecentCheckStrip onClick={(id) => navigate(`/report/${id}`)} />
          <Collapse ghost size="small" items={[{
            key: 'guide', label: <span style={{ color: 'var(--color-action)', fontSize: 13 }}>首次使用？查看操作指南</span>,
            children: (
              <div>
                <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap', marginBottom: 8 }}>
                  {[
                    { step: 1, title: '上传文件', desc: '拖拽或选择 PDF/Word 文件，系统自动上传' },
                    { step: 2, title: '文档解析', desc: '自动提取招标文件的章节结构' },
                    { step: 3, title: '五层审查', desc: '智能路由→规则引擎→参数倾向→AI语义→风险合并' },
                    { step: 4, title: '查看报告', desc: '获得合规评分和详细整改建议' },
                  ].map(({ step, title, desc }) => (
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
          <div style={{ textAlign: 'right', marginBottom: 8 }}>
            <Button type="link" size="small" onClick={() => setTourOpen(true)}>快速入门引导</Button>
          </div>
        </>
      )}

      {/* 上传区域 */}
      {!isRunning && !processingRef.current && files.length === 0 && (
        <div id="tour-upload-area" className={`upload-zone ${dragOver ? 'drag-over' : ''}`}
          onDragOver={e => { e.preventDefault(); if (!isRunning && !processingRef.current) setDragOver(true); }}
          onDragLeave={e => { e.preventDefault(); setDragOver(false); }}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}>
          <input ref={fileInputRef} type="file" accept=".pdf,.docx" multiple style={{ display: 'none' }} onChange={handleFileChange} />
          <InboxOutlined className="upload-zone-icon" />
          <div className="upload-zone-title">点击或拖拽招标文件到此处</div>
          <div className="upload-zone-hint">支持 PDF、DOCX 格式，系统将自动完成上传、解析、合规检查</div>
        </div>
      )}

      {/* 文件队列 */}
      {files.length > 0 && (
        <Card size="small" style={{ marginBottom: 16, borderRadius: 10, border: '1px solid var(--color-border)' }}
          styles={{ body: { padding: '12px 16px' } }}
          title={<Space><FileOutlined /><Text strong style={{ fontSize: 14 }}>文件列表</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {processingRef.current ? `正在处理 ${doneCount + 1}/${files.length} 份文件` :
                currentStep === 'done' ? `已完成 ${doneCount}/${files.length} 份文件` : `${files.length} 份文件`}
            </Text></Space>}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {files.map((item) => (
              <div key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 8px', borderRadius: 6,
                background: (item.status === 'uploading' || item.status === 'checking') ? 'var(--color-brand-light)' :
                  item.status === 'error' ? '#fff2f0' : 'transparent' }}>
                <FileStatusIcon status={item.status} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Text style={{ fontSize: 13, display: 'block' }} ellipsis>{item.file.name}</Text>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {(item.file.size / 1024 / 1024).toFixed(1)} MB · {STATUS_LABELS[item.status]}
                    {item.status === 'done' && item.result && ` · 评分 ${item.result.score}`}
                  </Text>
                  {item.status === 'error' && item.errorMsg && (
                    <Text type="danger" style={{ fontSize: 11, display: 'block' }}>{item.errorMsg}</Text>)}
                </div>
                {item.status === 'error' && <Button size="small" type="link" icon={<ReloadOutlined />} onClick={() => handleRetryFile(item.id)}>重试</Button>}
                {item.status === 'done' && item.result && <Button size="small" type="link" icon={<ArrowRightOutlined />} onClick={() => navigate(`/report/${item.result!.report_id}`)}>报告</Button>}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 过程轨道 */}
      {(isRunning || error || currentStep === 'done') && fileRef.current && (
        <Card style={{ marginBottom: 20, borderRadius: 12 }} styles={{ body: { padding: '24px 16px' } }} id="process-track">
          {fileRef.current && (
            <div style={{ marginBottom: 12, paddingLeft: 4 }}>
              <Space><Text type="secondary" style={{ fontSize: 12 }}>当前文件：</Text>
              <Text style={{ fontSize: 13, fontWeight: 500 }}>{fileRef.current.name}</Text></Space>
            </div>
          )}
          <div className="process-track">
            {STEPS.map((s, i) => (
              <React.Fragment key={s.key}>
                <ProcessNode step={s} status={getStepStatus(s.key)}
                  errorMsg={error?.step === s.key ? error.message : undefined}
                  onRetry={error?.step === s.key ? (s.key === 'uploading' ? () => handleRetryAll() : undefined) : undefined}
                  progressPct={getStepStatus(s.key) === 'active' ? Math.min(progress, 95) : getStepStatus(s.key) === 'done' ? 100 : 0} />
                {i < STEPS.length - 1 && (
                  <div className={`process-line ${getStepStatus(s.key) === 'done' ? 'done' : getStepStatus(s.key) === 'active' ? 'active' : ''}`} style={{ flexShrink: 0 }} />
                )}
              </React.Fragment>
            ))}
          </div>
          {error && error.step !== 'idle' && (
            <>
              <Alert message="检查未完成"
                description={<div><Text strong style={{ color: 'var(--color-error)' }}>{error.message}</Text>
                <div style={{ marginTop: 8 }}><Text type="secondary" style={{ fontSize: 13 }}>请检查文件是否符合要求后重新上传</Text></div></div>}
                type="error" showIcon style={{ marginTop: 12, borderRadius: 8 }} />
              <div style={{ textAlign: 'center', marginTop: 12 }}>
                <Space size={12}>
                  <Button onClick={resetAll} style={{ borderRadius: 8 }}>重新选择文件</Button>
                  <Button icon={<ReloadOutlined />} onClick={handleRetryAll} style={{ borderRadius: 8 }}>重试全部</Button>
                </Space>
              </div>
            </>
          )}
        </Card>
      )}

      {/* 单文件完成 */}
      {currentStep === 'done' && result && !isBatchMode && (
        <Result status="success" title="合规检查完成" subTitle="系统已完成对招标文件的全部合规审查"
          extra={[
            result.pipeline && (
              <Card key="pipeline" size="small" style={{ marginBottom: 16, borderRadius: 10, border: '1px solid var(--color-border)', textAlign: 'left', maxWidth: 480, margin: '0 auto 16px auto' }} styles={{ body: { padding: '14px 18px' } }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {[
                    { icon: <ThunderboltOutlined />, label: '智能路由', val: result.pipeline.traffic_light === 'green' ? '🟢 绿灯 · 跳过AI' : '🔴 红灯 · 进入AI审查' },
                    { icon: <SafetyOutlined />, label: '规则引擎', val: `命中${result.score < 85 ? '违规' : '0'}项` },
                    { icon: <FlagOutlined />, label: '参数倾向性', val: `发现${result.pipeline.parameter_bias_findings}个风险 · 得分${result.pipeline.parameter_bias_score}` },
                    { icon: <ExperimentOutlined />, label: 'AI语义', val: result.pipeline.traffic_light === 'green' ? '已跳过' : '分析完成' },
                    { icon: <MergeCellsOutlined />, label: '风险合并', val: `${result.pipeline.merge_risk_level} · ${result.pipeline.merge_review_status}${result.pipeline.merge_requires_human_review ? ' · 需人工复核' : ' · 自动通过'}` },
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
              <Tag color={result.score >= 85 ? 'green' : result.score >= 60 ? 'gold' : 'red'} style={{ padding: '4px 16px', borderRadius: 20, fontSize: 16 }}>合规评分：{result.score}</Tag>
            </div>,
            <Button key="report" type="primary" size="large" icon={<ArrowRightOutlined />} onClick={() => navigate(`/report/${result.report_id}`)} style={{ borderRadius: 8, paddingLeft: 28, paddingRight: 28 }}>查看详细报告</Button>,
            <Button key="new" onClick={resetAll} style={{ borderRadius: 8 }}>检查新文件</Button>,
          ]} />
      )}

      {/* 批完成 */}
      {currentStep === 'done' && isBatchMode && (
        <Card style={{ borderRadius: 12, marginBottom: 20 }} styles={{ body: { padding: '24px 20px', textAlign: 'center' } }}>
          <CheckCircleOutlined style={{ fontSize: 48, color: 'var(--color-success)', marginBottom: 12 }} />
          <Title level={4} style={{ marginBottom: 4 }}>全部检查完成</Title>
          <Text type="secondary" style={{ display: 'block', marginBottom: 20 }}>已完成 {files.filter(f => f.status === 'done').length}/{files.length} 份文件的合规审查</Text>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 500, margin: '0 auto 20px auto', textAlign: 'left' }}>
            {files.map((item) => (
              <div key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8,
                background: item.status === 'done' ? 'var(--color-bg)' : '#fff2f0', border: '1px solid var(--color-border)' }}>
                {item.status === 'done' ? <CheckCircleOutlined style={{ color: 'var(--color-success)', fontSize: 16 }} /> : <CloseCircleOutlined style={{ color: 'var(--color-error)', fontSize: 16 }} />}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Text style={{ fontSize: 13, display: 'block' }} ellipsis>{item.file.name}</Text>
                  {item.status === 'done' && item.result && <Tag color={item.result.score >= 85 ? 'green' : item.result.score >= 60 ? 'gold' : 'red'} style={{ marginTop: 2, fontSize: 11 }}>评分 {item.result.score}</Tag>}
                  {item.status === 'error' && <Text type="danger" style={{ fontSize: 11, display: 'block' }}>{item.errorMsg || '处理失败'}</Text>}
                </div>
                {item.status === 'done' && item.result && <Button size="small" type="primary" ghost icon={<ArrowRightOutlined />} onClick={() => navigate(`/report/${item.result!.report_id}`)}>查看报告</Button>}
                {item.status === 'error' && <Button size="small" type="link" icon={<ReloadOutlined />} onClick={() => handleRetryFile(item.id)}>重试</Button>}
              </div>
            ))}
          </div>
          <Space><Button type="primary" size="large" onClick={resetAll} style={{ borderRadius: 8, paddingLeft: 28, paddingRight: 28 }}>检查新文件</Button></Space>
        </Card>
      )}

      {error?.step === 'idle' && (
        <Alert message="文件校验失败" description={error.message} type="error" showIcon style={{ marginTop: 16, borderRadius: 8 }} closable onClose={() => setError(null)} />
      )}

      <Tour open={tourOpen} onClose={() => setTourOpen(false)} steps={tourSteps} />
    </div>
  );
};

export default UploadPage;
