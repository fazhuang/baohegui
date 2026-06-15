/**
 * UploadPage — 文件上传与五层审查
 *
 * 编排层：使用 features/upload 的队列状态和组件。
 * 视图组件已拆分到 features/upload/components/。
 */

import React, { useState, useRef } from 'react';
import {
  Card, Typography, Button, Alert, Space, Tour,
} from 'antd';
import {
  InboxOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { STEPS, MAX_BATCH } from '../features/upload/types';
import { useUploadQueue } from '../features/upload/hooks/useUploadQueue';
import { ProcessNode } from '../features/upload/components';
import RecentCheckStrip from '../features/upload/components/RecentCheckStrip';
import StepGuide from '../features/upload/components/StepGuide';
import FileList from '../features/upload/components/FileList';
import BatchDoneCard from '../features/upload/components/BatchDoneCard';
import SingleDoneResult from '../features/upload/components/SingleDoneResult';

const { Title, Text } = Typography;

const VALID_EXTENSIONS = ['pdf', 'docx'];
const MAX_FILE_MB = 50;

const TOUR_STEPS = [
  { title: '包合规操作指南', description: '帮助您在提交前发现合规问题。只需三步。', target: () => document.getElementById('tour-upload-area') as HTMLElement, placement: 'bottom' as const },
  { title: '上传文件', description: '拖拽招标文件到上传区域。支持 PDF 和 Word。', target: () => document.getElementById('tour-upload-area') as HTMLElement, placement: 'bottom' as const },
  { title: '查看操作指南', description: '点击此处查看详细的操作说明。', target: () => document.querySelector('.ant-collapse-header') as HTMLElement, placement: 'right' as const },
  { title: '等待检查', description: '自动完成上传→解析→五层审查流水线', target: () => document.getElementById('process-track') as HTMLElement, placement: 'top' as const },
];

const UploadPage: React.FC = () => {
  const navigate = useNavigate();
  const queue = useUploadQueue();
  const { files, currentStep, error, result, progress, isRunning, isBatchMode, doneCount,
    processingRef, fileRef, addFiles, handleRetryFile, handleRetryAll, resetAll, setError, getStepStatus } = queue;

  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [tourOpen, setTourOpen] = useState(false);

  const validateExt = (file: File): boolean => {
    const ext = file.name.split('.').pop()?.toLowerCase();
    return VALID_EXTENSIONS.includes(ext || '');
  };

  const validateFiles = (fileList: File[]): File[] => {
    for (const file of fileList.slice(0, MAX_BATCH)) {
      if (!validateExt(file)) {
        setError({ step: 'idle', message: `"${file.name}" 格式不支持，仅支持 PDF 和 Word (.docx)` });
        return [];
      }
      if (file.size > MAX_FILE_MB * 1024 * 1024) {
        setError({ step: 'idle', message: `"${file.name}" 超过 ${MAX_FILE_MB}MB 大小限制` });
        return [];
      }
    }
    return fileList.slice(0, MAX_BATCH);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragOver(false);
    if (isRunning || processingRef.current) return;
    const valid = validateFiles(Array.from(e.dataTransfer.files));
    if (valid.length > 0) addFiles(valid);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files;
    if (!selected || selected.length === 0 || isRunning || processingRef.current) return;
    const valid = validateFiles(Array.from(selected));
    e.target.value = '';
    if (valid.length > 0) addFiles(valid);
  };

  const renderProcessError = () => (
    <>
      <Alert message="检查未完成"
        description={<div><Text strong style={{ color: 'var(--color-error)' }}>{error!.message}</Text>
        <div style={{ marginTop: 8 }}><Text type="secondary" style={{ fontSize: 13 }}>请检查文件是否符合要求后重新上传</Text></div></div>}
        type="error" showIcon style={{ marginTop: 12, borderRadius: 8 }} />
      <div style={{ textAlign: 'center', marginTop: 12 }}>
        <Space size={12}>
          <Button onClick={resetAll} style={{ borderRadius: 8 }}>重新选择文件</Button>
          <Button icon={<ReloadOutlined />} onClick={handleRetryAll} style={{ borderRadius: 8 }}>重试全部</Button>
        </Space>
      </div>
    </>
  );

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
        支持 PDF 和 Word 格式，单文件不超过 {MAX_FILE_MB}MB，最多 {MAX_BATCH} 份文件
      </Text>

      {/* 空闲态：最近检查 + 使用指南 */}
      {currentStep === 'idle' && files.length === 0 && (
        <>
          <RecentCheckStrip onClick={(id) => navigate(`/report/${id}`)} />
          <StepGuide />
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
        <FileList
          files={files}
          isRunning={isRunning}
          processingRef={processingRef}
          currentStep={currentStep}
          doneCount={doneCount}
          onRetryFile={handleRetryFile}
          onNavigateReport={(id) => navigate(`/report/${id}`)}
        />
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
          {error && error.step !== 'idle' && renderProcessError()}
        </Card>
      )}

      {/* 单文件完成 */}
      {currentStep === 'done' && result && !isBatchMode && (
        <SingleDoneResult
          score={result.score}
          reportId={result.report_id}
          pipeline={result.pipeline}
          onViewReport={(id) => navigate(`/report/${id}`)}
          onReset={resetAll}
        />
      )}

      {/* 批量完成 */}
      {currentStep === 'done' && isBatchMode && (
        <BatchDoneCard
          files={files}
          onNavigateReport={(id) => navigate(`/report/${id}`)}
          onRetryFile={handleRetryFile}
          onReset={resetAll}
        />
      )}

      {error?.step === 'idle' && (
        <Alert message="文件校验失败" description={error.message} type="error" showIcon style={{ marginTop: 16, borderRadius: 8 }} closable onClose={() => setError(null)} />
      )}

      <Tour open={tourOpen} onClose={() => setTourOpen(false)} steps={TOUR_STEPS} />
    </div>
  );
};

export default UploadPage;
