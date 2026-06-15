/**
 * RecentCheckStrip — 最近检查概览条
 *
 * 从 Upload.tsx 拆分到 features/upload/components。
 */

import React, { useState } from 'react';
import { Typography } from 'antd';
import { HistoryOutlined } from '@ant-design/icons';
import { listReports } from '../../../services/api';
import type { ReportListItem } from '../../../types';

const { Text } = Typography;

interface RecentCheckStripProps {
  onClick?: (id: number) => void;
}

const RecentCheckStrip: React.FC<RecentCheckStripProps> = ({ onClick }) => {
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

export default RecentCheckStrip;
