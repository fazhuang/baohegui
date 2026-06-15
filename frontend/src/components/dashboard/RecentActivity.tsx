/**
 * RecentActivity — Dashboard 最近活动列表
 *
 * 使用方式:
 *   <RecentActivity
 *     items={reports}
 *     emptyText="暂无审查记录"
 *     onItemClick={id => navigate(`/report/${id}`)}
 *     onViewAll={() => navigate('/review/history')}
 *   />
 */

import React from 'react';
import { Card, Button, Typography, Skeleton, Empty } from 'antd';
import { ArrowRightOutlined } from '@ant-design/icons';
import StatusTag from '../StatusTag';

const { Text } = Typography;

interface ActivityItem {
  id: number | string;
  title: string;
  time: string;
  riskLevel?: string;
  status?: string;
}

interface RecentActivityProps {
  title?: string;
  items: ActivityItem[];
  loading?: boolean;
  emptyText?: string;
  onItemClick?: (id: number | string) => void;
  onViewAll?: () => void;
}

const RecentActivity: React.FC<RecentActivityProps> = ({
  title = '最近活动',
  items,
  loading,
  emptyText = '暂无数据',
  onItemClick,
  onViewAll,
}) => {
  return (
    <Card
      title={<Text strong style={{ fontSize: 15 }}>{title}</Text>}
      extra={
        onViewAll && (
          <Button type="link" size="small" onClick={onViewAll}>
            查看全部 <ArrowRightOutlined />
          </Button>
        )
      }
      style={{ borderRadius: 12 }}
      styles={{ body: { padding: '8px 16px 16px' } }}
    >
      {loading ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : items.length > 0 ? (
        <div style={{ maxHeight: 320, overflowY: 'auto' }}>
          {items.map((item, idx) => (
            <div
              key={idx}
              onClick={() => onItemClick?.(item.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 12px',
                borderRadius: 8,
                cursor: onItemClick ? 'pointer' : 'default',
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = '#f8fafc'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <Text style={{ fontSize: 13 }} ellipsis>{item.title}</Text>
                <br />
                <Text type="secondary" style={{ fontSize: 11 }}>{item.time}</Text>
              </div>
              {item.riskLevel && <StatusTag riskLevel={item.riskLevel} />}
              {item.status && <StatusTag status={item.status} />}
            </div>
          ))}
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} style={{ padding: '24px 0' }} />
      )}
    </Card>
  );
};

export default RecentActivity;
