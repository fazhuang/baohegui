/**
 * FeedbackTab — 拦截反馈管理 Tab 视图
 *
 * 从 AdminRules.tsx 拆分到 features/rules/components。
 */

import React, { useState } from 'react';
import { Table, Button, Space, Spin, Empty, message } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';
import type { PlatformRule } from '../../../types';
import { listPlatformRules, updatePlatformRule, deletePlatformRule } from '../../../services/api';

const FeedbackTab: React.FC = () => {
  const [drafts, setDrafts] = useState<PlatformRule[]>([]);
  const [loading, setLoading] = useState(true);

  const loadDrafts = React.useCallback(async () => {
    setLoading(true);
    try {
      const data = await listPlatformRules({ search: 'draft' });
      setDrafts(data.rules.filter(r => r.category === 'draft'));
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  React.useEffect(() => { loadDrafts(); }, [loadDrafts]);

  const handleActivate = async (r: PlatformRule) => {
    await updatePlatformRule(r.rule_id, { enabled: true, category: 'custom' });
    message.success('规则已启用'); loadDrafts();
  };

  if (loading) return <Spin style={{ display: 'block', textAlign: 'center', padding: 40 }} />;

  return (
    <div>
      {drafts.length === 0 ? (
        <Empty description="暂无拦截反馈" />
      ) : (
        <Table dataSource={drafts} rowKey="rule_id" size="small"
          columns={[
            { title: '规则 ID', dataIndex: 'rule_id', key: 'rule_id', width: 150 },
            { title: '平台', dataIndex: 'platform', key: 'platform', width: 160 },
            { title: '代码', dataIndex: 'platform_code', key: 'platform_code', width: 100 },
            { title: '描述', dataIndex: 'description', key: 'description' },
            { title: '提交时间', dataIndex: 'effective_date', key: 'date', width: 120 },
            { title: '操作', key: 'action', width: 180,
              render: (_: unknown, r: PlatformRule) => (
                <Space>
                  <Button size="small" type="primary" icon={<CheckCircleOutlined />} onClick={() => handleActivate(r)}>转为规则</Button>
                  <Button size="small" danger icon={<CloseCircleOutlined />} onClick={async () => { await deletePlatformRule(r.rule_id); message.success('已忽略'); loadDrafts(); }}>忽略</Button>
                </Space>
              ) },
          ]} />
      )}
    </div>
  );
};

export default FeedbackTab;
