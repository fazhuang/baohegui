/**
 * FileStatusIcon — 文件状态图标组件
 *
 * 从 Upload.tsx 拆分。
 */

import React from 'react';
import { CheckCircleOutlined, CloseCircleOutlined, FileOutlined, LoadingOutlined } from '@ant-design/icons';
import type { FileItemData } from '../types';

const FileStatusIcon: React.FC<{ status: FileItemData['status'] }> = ({ status }) => {
  switch (status) {
    case 'pending': return <FileOutlined style={{ color: 'var(--color-text-tertiary)' }} />;
    case 'uploading': case 'checking': return <LoadingOutlined style={{ color: 'var(--color-action)' }} />;
    case 'done': return <CheckCircleOutlined style={{ color: 'var(--color-success)' }} />;
    case 'error': return <CloseCircleOutlined style={{ color: 'var(--color-error)' }} />;
  }
};

export default FileStatusIcon;

export const STATUS_LABELS: Record<FileItemData['status'], string> = {
  pending: '等待中', uploading: '上传中', checking: '检查中', done: '已完成', error: '失败',
};
