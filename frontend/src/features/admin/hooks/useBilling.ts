/** Admin feature — 计费看板状态 hook */

import { useState, useCallback, useEffect } from 'react';
import { message } from 'antd';
import { getBillingStatus, getBillingThreshold, setBillingThreshold } from '../../../services/api';
import type { BillingStatus } from '../../../types';
import { getErrorMessage } from '../../../utils/error';

export function useBilling() {
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [threshold, setThreshold] = useState({ max_monthly_tokens: 1000000, max_monthly_cost_yuan: 100, alert_threshold_pct: 80 });
  const [editingThreshold, setEditingThreshold] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([getBillingStatus(), getBillingThreshold()]);
      setStatus(s);
      setThreshold(t);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSaveThreshold = async () => {
    setSaving(true);
    try {
      await setBillingThreshold(threshold);
      message.success('阈值已保存');
      setEditingThreshold(false);
      load();
    } catch (e: unknown) { message.error(getErrorMessage(e, '保存失败')); }
    finally { setSaving(false); }
  };

  return { status, threshold, editingThreshold, saving, setThreshold, setEditingThreshold, handleSaveThreshold, load };
}
