/**
 * RuleListTab — 规则列表 Tab 视图
 *
 * 从 AdminRules.tsx 拆分到 features/rules/components。
 */

import React from 'react';
import {
  Table, Tag, Button, Space, Typography, Input, Select, Modal, Form, Switch, message, Popconfirm,
} from 'antd';
import {
  ReloadOutlined, PlusOutlined, DeleteOutlined, EditOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import type { PlatformRule } from '../../../types';
import { createPlatformRule } from '../../../services/api';
import { useRuleList } from '../hooks';

const { Text } = Typography;

// ── 颜色映射 ────────────────────────────────────────────────
const typeColor: Record<string, string> = {
  chapter: 'blue', keyword: 'geekblue', forbidden: 'red', semantic: 'purple', unknown: 'default',
};
const typeLabel: Record<string, string> = {
  chapter: '章节', keyword: '关键字', forbidden: '禁用词', semantic: '语义', unknown: '未知',
};
const categoryLabel: Record<string, string> = {
  base: '基础', platform: '平台', industry: '行业', custom: '自定义', draft: '草稿',
};

const RuleListTab: React.FC = () => {
  const {
    loading, search, editRule, editOpen, createOpen, filtered,
    setSearch, setTypeFilter, setEditRule, setEditOpen, setCreateOpen,
    loadRules, handleToggle, handleDelete, handleEdit, handleReload,
  } = useRuleList();

  return (
    <div>
      <Space style={{ marginBottom: 16, flexWrap: 'wrap' }}>
        <Input prefix={<SearchOutlined />} placeholder="搜索规则 ID/描述..."
          value={search} onChange={e => setSearch(e.target.value)} style={{ width: 240 }} allowClear />
        <Select placeholder="类型筛选" allowClear style={{ width: 120 }}
          options={[
            { value: 'chapter', label: '章节' }, { value: 'keyword', label: '关键字' },
            { value: 'forbidden', label: '禁用词' }, { value: 'semantic', label: '语义' },
          ]} onChange={v => setTypeFilter(v || null)} />
        <Button icon={<PlusOutlined />} type="primary" onClick={() => setCreateOpen(true)}>新建规则</Button>
        <Button icon={<ReloadOutlined />} onClick={handleReload}>热加载</Button>
      </Space>

      <Table dataSource={filtered} rowKey="rule_id" loading={loading} size="small" pagination={{ pageSize: 20 }}
        columns={[
          { title: '规则 ID', dataIndex: 'rule_id', key: 'rule_id', width: 130 },
          { title: '类型', dataIndex: 'rule_type', key: 'rule_type', width: 80,
            render: (v: string) => <Tag color={typeColor[v]}>{typeLabel[v]}</Tag> },
          { title: '目标', dataIndex: 'target', key: 'target', width: 120 },
          { title: '描述', dataIndex: 'description', key: 'description' },
          { title: '分类', dataIndex: 'category', key: 'category', width: 80,
            render: (v: string) => <Tag>{categoryLabel[v] || v}</Tag> },
          { title: '版本', dataIndex: 'version', key: 'version', width: 60 },
          { title: '启用', dataIndex: 'enabled', key: 'enabled', width: 60,
            render: (v: boolean, r: PlatformRule) => <Switch size="small" checked={v} onChange={() => handleToggle(r.rule_id)} /> },
          { title: '操作', key: 'action', width: 120,
            render: (_: unknown, r: PlatformRule) => (
              <Space>
                <Button size="small" icon={<EditOutlined />} onClick={() => { setEditRule(r); setEditOpen(true); }} />
                <Popconfirm title="确认删除？" onConfirm={() => handleDelete(r.rule_id)}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ) },
        ]} />

      <Modal title="编辑规则" open={editOpen} onCancel={() => setEditOpen(false)} footer={null} width={560}>
        {editRule && (
          <Form layout="vertical" initialValues={editRule} onFinish={handleEdit}>
            <Form.Item label="规则 ID"><Text code>{editRule.rule_id}</Text></Form.Item>
            <Form.Item label="描述" name="description"><Input.TextArea rows={2} /></Form.Item>
            <Form.Item label="类型" name="rule_type">
              <Select options={[{ value: 'chapter', label: '章节' }, { value: 'keyword', label: '关键字' }, { value: 'forbidden', label: '禁用词' }, { value: 'semantic', label: '语义' }]} />
            </Form.Item>
            <Form.Item label="目标" name="target"><Input /></Form.Item>
            <Form.Item label="分类" name="category">
              <Select options={[{ value: 'base', label: '基础' }, { value: 'platform', label: '平台' }, { value: 'draft', label: '草稿' }]} />
            </Form.Item>
            <Form.Item label="版本号" name="version"><Input /></Form.Item>
            <Form.Item><Button type="primary" htmlType="submit">保存</Button></Form.Item>
          </Form>
        )}
      </Modal>

      <Modal title="新建规则" open={createOpen} onCancel={() => setCreateOpen(false)} footer={null} width={560}>
        <Form layout="vertical" onFinish={async (v: Partial<PlatformRule>) => {
          await createPlatformRule(v); message.success('规则已创建'); setCreateOpen(false); loadRules();
        }}>
          <Form.Item label="规则 ID" name="rule_id" rules={[{ required: true }]}><Input placeholder="如: CUSTOM-001" /></Form.Item>
          <Form.Item label="平台" name="platform" initialValue="自定义"><Input /></Form.Item>
          <Form.Item label="平台代码" name="platform_code"><Input placeholder="如: CUS-001" /></Form.Item>
          <Form.Item label="类型" name="rule_type" initialValue="forbidden">
            <Select options={[{ value: 'chapter', label: '章节' }, { value: 'keyword', label: '关键字' }, { value: 'forbidden', label: '禁用词' }]} />
          </Form.Item>
          <Form.Item label="描述" name="description"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item label="目标" name="target"><Input /></Form.Item>
          <Form.Item><Button type="primary" htmlType="submit">创建</Button></Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default RuleListTab;
