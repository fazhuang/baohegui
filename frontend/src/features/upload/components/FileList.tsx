/**
 * FileList — 上传文件队列卡片
 *
 * 从 Upload.tsx 拆分。
 */

import React from 'react';
import { Card, Typography, Button, Space } from 'antd';
import { FileOutlined, ArrowRightOutlined, ReloadOutlined } from '@ant-design/icons';
import type { FileItemData } from '../types';
import FileStatusIcon, { STATUS_LABELS } from './FileStatusIcon';

const { Text } = Typography;

interface FileListProps {
  files: FileItemData[];
  isRunning: boolean;
  processingRef: React.RefObject<boolean | null>;
  currentStep: string;
  doneCount: number;
  onRetryFile: (id: number) => void;
  onNavigateReport: (id: number) => void;
}

const FileList: React.FC<FileListProps> = ({
  files, processingRef, currentStep, doneCount,
  onRetryFile, onNavigateReport,
}) => (
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
          {item.status === 'error' && <Button size="small" type="link" icon={<ReloadOutlined />} onClick={() => onRetryFile(item.id)}>重试</Button>}
          {item.status === 'done' && item.result && <Button size="small" type="link" icon={<ArrowRightOutlined />} onClick={() => onNavigateReport(item.result!.report_id)}>报告</Button>}
        </div>
      ))}
    </div>
  </Card>
);

export default FileList;
