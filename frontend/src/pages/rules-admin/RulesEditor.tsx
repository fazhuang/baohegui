/**
 * RulesEditor — 规则编辑器页面
 *
 * 编排层：导入 features/rules/components 下的 RuleDetailModal 和 RulesEditorToolbar。
 */

import React, { useEffect, useState, useCallback } from 'react';
import {
  Table, Tag, Button, Typography, Spin, Empty, Card, Tooltip, message,
} from 'antd';
import {
  ReloadOutlined, EditOutlined, AppstoreAddOutlined,
} from '@ant-design/icons';
import { fetchAllRules, batchToggleRules } from '../../services/api';
import { getErrorMessage } from '../../utils/error';
import RuleDetailModal from '../../features/rules/components/RuleDetailModal';
import type { RuleRecord } from '../../features/rules/components/RuleDetailModal';
import RulesEditorToolbar from '../../features/rules/components/RulesEditorToolbar';

const { Title, Text } = Typography;

const TYPE_COLOR: Record<string, string> = {
  chapter: 'blue', keyword: 'geekblue', forbidden: 'red', semantic: 'purple',
  pattern_required: 'cyan', required: 'green', conditional: 'orange', unknown: 'default',
};

const TYPE_LABEL: Record<string, string> = {
  chapter: '章节', keyword: '关键字', forbidden: '禁用词', semantic: '语义',
  pattern_required: '模式匹配', required: '必填', conditional: '条件', unknown: '未知',
};

const CATEGORY_COLOR: Record<string, string> = {
  base: 'blue', platform: 'green', industry: 'purple', custom: 'orange', draft: 'default',
};

const CATEGORY_LABEL: Record<string, string> = {
  base: '基础', platform: '平台', industry: '行业', custom: '自定义', draft: '草稿',
  qualification: '资格条件', evaluation: '评标标准', commercial: '商务条款',
  procedural: '程序合规', legal_conflict: '法规冲突',
};

interface RuleListResponse { total: number; rules: RuleRecord[]; }

const RulesEditor: React.FC = () => {
  const [rules, setRules] = useState<RuleRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [batchLoading, setBatchLoading] = useState(false);
  const [detailRule, setDetailRule] = useState<RuleRecord | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data: RuleListResponse = await fetchAllRules(search || undefined);
      setRules(data.rules || []);
    } catch (e: unknown) {
      message.error('加载规则列表失败');
      setError(getErrorMessage(e, '加载规则列表失败'));
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => {
    const timer = setTimeout(load, 300);
    return () => clearTimeout(timer);
  }, [load]);

  const handleBatchToggle = async (enabled: boolean) => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要操作的规则');
      return;
    }
    setBatchLoading(true);
    try {
      const result = await batchToggleRules(selectedRowKeys as string[], enabled);
      message.success(enabled ? `已启用 ${result.toggled} 条规则` : `已停用 ${result.toggled} 条规则`);
      setSelectedRowKeys([]);
      load();
    } catch (e: unknown) {
      message.error(`批量操作失败: ${getErrorMessage(e, '批量操作失败')}`);
    } finally {
      setBatchLoading(false);
    }
  };

  // ── Loading / Error states ──
  if (loading && rules.length === 0) {
    return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" tip="加载规则列表..." /></div>;
  }

  if (error && rules.length === 0) {
    return (
      <div>
        <Title level={3}><AppstoreAddOutlined style={{ marginRight: 8 }} />规则编辑器</Title>
        <Card>
          <Empty description={`加载失败: ${error}`} image={Empty.PRESENTED_IMAGE_SIMPLE}>
            <Button icon={<ReloadOutlined />} onClick={load}>重试</Button>
          </Empty>
        </Card>
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}><AppstoreAddOutlined style={{ marginRight: 8 }} />规则编辑器</Title>
          <Text type="secondary">查看、搜索和批量管理规则</Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
      </div>

      <RulesEditorToolbar
        search={search}
        selectedCount={selectedRowKeys.length}
        batchLoading={batchLoading}
        onSearchChange={setSearch}
        onBatchToggle={handleBatchToggle}
      />

      <Card style={{ borderRadius: 10 }}>
        {rules.length === 0 ? (
          <Empty description={search ? `未找到匹配 "${search}" 的规则` : '暂无规则'} image={Empty.PRESENTED_IMAGE_SIMPLE}>
            {search && <Button onClick={() => setSearch('')}>清除搜索</Button>}
          </Empty>
        ) : (
          <Table
            rowSelection={{ selectedRowKeys, onChange: (keys) => setSelectedRowKeys(keys) }}
            dataSource={rules}
            rowKey="rule_id"
            size="middle"
            loading={loading}
            pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (total) => `共 ${total} 条规则` }}
            columns={[
              { title: '规则 ID', dataIndex: 'rule_id', key: 'rule_id', width: 140, ellipsis: true,
                render: (v: string, r: RuleRecord) => (
                  <Button type="link" size="small" onClick={() => { setDetailRule(r); setDetailOpen(true); }} style={{ padding: 0 }}>
                    <Text code style={{ fontSize: 12 }}>{v}</Text>
                  </Button>
                ) },
              { title: '类型', dataIndex: 'rule_type', key: 'rule_type', width: 90,
                render: (v: string) => <Tag color={TYPE_COLOR[v] || 'default'}>{TYPE_LABEL[v] || v}</Tag> },
              { title: '目标字段', dataIndex: 'target', key: 'target', width: 120, ellipsis: true,
                render: (v: string) => v || '-' },
              { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
              { title: '分类', dataIndex: 'category', key: 'category', width: 90,
                render: (v: string) => <Tag color={CATEGORY_COLOR[v] || 'default'}>{CATEGORY_LABEL[v] || v}</Tag> },
              { title: '版本', dataIndex: 'version', key: 'version', width: 70 },
              { title: '启用', dataIndex: 'enabled', key: 'enabled', width: 70,
                render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '是' : '否'}</Tag> },
              { title: '操作', key: 'action', width: 80,
                render: (_: unknown, r: RuleRecord) => (
                  <Tooltip title="查看详情">
                    <Button size="small" icon={<EditOutlined />} onClick={() => { setDetailRule(r); setDetailOpen(true); }} />
                  </Tooltip>
                ) },
            ]}
          />
        )}
      </Card>

      <RuleDetailModal open={detailOpen} rule={detailRule} onClose={() => setDetailOpen(false)} />
    </div>
  );
};

export default RulesEditor;
