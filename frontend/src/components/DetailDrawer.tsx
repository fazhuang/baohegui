/**
 * DetailDrawer — 右侧滑出详情面板
 *
 * 用于列表页查看详情而不跳页。
 *
 * 使用方式:
 *   <DetailDrawer open={open} onClose={() => setOpen(false)} title="报告详情" width={640}>
 *     <ReportDetail reportId={selectedId} />
 *   </DetailDrawer>
 */

import React from 'react';
import { Drawer, Typography } from 'antd';
import { CloseOutlined } from '@ant-design/icons';

const { Title } = Typography;

interface DetailDrawerProps {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  width?: number;
  children: React.ReactNode;
  extra?: React.ReactNode;
}

const DetailDrawer: React.FC<DetailDrawerProps> = ({
  open, onClose, title, subtitle, width = 640, children, extra,
}) => {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={width}
      placement="right"
      closable={false}
      extra={<CloseOutlined onClick={onClose} style={{ cursor: 'pointer', fontSize: 16 }} />}
      title={
        <div>
          <Title level={5} style={{ margin: 0 }}>{title}</Title>
          {subtitle && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {subtitle}
            </Typography.Text>
          )}
        </div>
      }
      footer={extra ? <div style={{ textAlign: 'right' }}>{extra}</div> : undefined}
      styles={{
        body: { padding: '16px 24px' },
        header: { borderBottom: '1px solid #f0f0f0' },
        footer: { borderTop: '1px solid #f0f0f0' },
      }}
    >
      {children}
    </Drawer>
  );
};

export default DetailDrawer;
