/**
 * RuleDetailModal — 规则详情弹窗
 *
 * 从 RulesEditor.tsx 拆分。
 */

import React from 'react';
import { Modal, Descriptions, Tag, Switch, Button, Space, Typography } from 'antd';
import { EditOutlined } from '@ant-design/icons';

const { Text } = Typography;

// ── Colour maps ──────────────────────────────────────────────

const TYPE_COLOR: Record<string, string> = {
  chapter: 'blue',
  keyword: 'geekblue',
  forbidden: 'red',
  semantic: 'purple',
  pattern_required: 'cyan',
  required: 'green',
  conditional: 'orange',
  unknown: 'default',
};

const TYPE_LABEL: Record<string, string> = {
  chapter: '章节',
  keyword: '关键字',
  forbidden: '禁用词',
  semantic: '语义',
  pattern_required: '模式匹配',
  required: '必填',
  conditional: '条件',
  unknown: '未知',
};

const CATEGORY_COLOR: Record<string, string> = {
  base: 'blue',
  platform: 'green',
  industry: 'purple',
  custom: 'orange',
  draft: 'default',
};

const CATEGORY_LABEL: Record<string, string> = {
  base: '基础',
  platform: '平台',
  industry: '行业',
  custom: '自定义',
  draft: '草稿',
  qualification: '资格条件',
  evaluation: '评标标准',
  commercial: '商务条款',
  procedural: '程序合规',
  legal_conflict: '法规冲突',
};

export interface RuleRecord {
  rule_id: string;
  platform: string;
  platform_code: string;
  rule_type: string;
  target: string;
  mandatory: boolean;
  description: string;
  version: string;
  effective_date: string;
  enabled: boolean;
  category: string;
}

interface RuleDetailModalProps {
  open: boolean;
  rule: RuleRecord | null;
  onClose: () => void;
}

const RuleDetailModal: React.FC<RuleDetailModalProps> = ({ open, rule, onClose }) => (
  <Modal
    title={
      <Space>
        <EditOutlined />
        <span>规则详情</span>
        {rule && <Tag color="blue">{rule.rule_id}</Tag>}
      </Space>
    }
    open={open}
    onCancel={onClose}
    footer={[
      <Button key="close" onClick={onClose}>关闭</Button>,
    ]}
    width={640}
  >
    {rule && (
      <Descriptions column={1} bordered size="small" style={{ marginTop: 8 }}>
        <Descriptions.Item label="规则 ID">
          <Text code>{rule.rule_id}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="平台">
          {rule.platform || '-'}
        </Descriptions.Item>
        <Descriptions.Item label="平台代码">
          {rule.platform_code || '-'}
        </Descriptions.Item>
        <Descriptions.Item label="类型">
          <Tag color={TYPE_COLOR[rule.rule_type] || 'default'}>
            {TYPE_LABEL[rule.rule_type] || rule.rule_type}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="目标字段">
          {rule.target || '-'}
        </Descriptions.Item>
        <Descriptions.Item label="强制">
          <Tag color={rule.mandatory ? 'red' : 'green'}>
            {rule.mandatory ? '是' : '否'}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="描述" span={2}>
          {rule.description || '-'}
        </Descriptions.Item>
        <Descriptions.Item label="分类">
          <Tag color={CATEGORY_COLOR[rule.category] || 'default'}>
            {CATEGORY_LABEL[rule.category] || rule.category}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="版本">
          {rule.version || '-'}
        </Descriptions.Item>
        <Descriptions.Item label="生效日期">
          {rule.effective_date
            ? new Date(rule.effective_date).toLocaleDateString('zh-CN')
            : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="启用状态">
          <Switch
            checked={rule.enabled}
            disabled
            checkedChildren="启用"
            unCheckedChildren="停用"
          />
        </Descriptions.Item>
      </Descriptions>
    )}
  </Modal>
);

export default RuleDetailModal;
