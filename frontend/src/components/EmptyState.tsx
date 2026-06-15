/**
 * EmptyState — 统一空状态占位
 *
 * 使用方式:
 *   <EmptyState description="暂无审查记录" actionLabel="开始审查" onAction={() => navigate('/review')} />
 */

import React from 'react';
import { Empty, Button } from 'antd';

interface EmptyStateProps {
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  image?: React.ReactNode;
}

const EmptyState: React.FC<EmptyStateProps> = ({
  description = '暂无数据',
  actionLabel,
  onAction,
  image,
}) => {
  return (
    <Empty
      image={image ?? Empty.PRESENTED_IMAGE_SIMPLE}
      description={description}
      style={{ padding: '48px 0' }}
    >
      {actionLabel && onAction && (
        <Button type="primary" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </Empty>
  );
};

export default EmptyState;
