/** Rules feature — 规则列表 Tab 状态 hook */

import { useState, useCallback, useEffect } from 'react';
import { message } from 'antd';
import {
  listPlatformRules, togglePlatformRule, deletePlatformRule,
  updatePlatformRule, reloadRules,
} from '../../../services/api';
import type { PlatformRule } from '../../../types';

export function useRuleList() {
  const [rules, setRules] = useState<PlatformRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [editRule, setEditRule] = useState<PlatformRule | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  const loadRules = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listPlatformRules({ search: search || undefined });
      setRules(data.rules);
    } catch { message.error('加载规则失败'); }
    setLoading(false);
  }, [search]);

  useEffect(() => { loadRules(); }, [loadRules]);

  const handleToggle = async (id: string) => {
    const enabled = await togglePlatformRule(id);
    message.success(`规则已${enabled ? '启用' : '停用'}`);
    loadRules();
  };

  const handleDelete = async (id: string) => {
    await deletePlatformRule(id);
    message.success('规则已删除');
    loadRules();
  };

  const handleEdit = async (values: Partial<PlatformRule>) => {
    if (!editRule) return;
    await updatePlatformRule(editRule.rule_id, values);
    message.success('规则已更新');
    setEditOpen(false);
    loadRules();
  };

  const filtered = rules.filter(r => !typeFilter || r.rule_type === typeFilter);

  return {
    rules, loading, search, typeFilter, editRule, editOpen, createOpen, filtered,
    setSearch, setTypeFilter, setEditRule, setEditOpen, setCreateOpen,
    loadRules, handleToggle, handleDelete, handleEdit,
    handleReload: () => { reloadRules(); loadRules(); },
  };
}
