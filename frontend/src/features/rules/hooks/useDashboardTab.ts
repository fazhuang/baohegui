/** Rules feature — 系统看板 Tab 状态 hook */

import { useState, useCallback, useEffect } from 'react';
import { message } from 'antd';
import { getDashboardStats } from '../../../services/api';
import type { DashboardStats } from '../../../types';

export function useDashboardTab() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(async () => {
    setLoading(true);
    try { setStats(await getDashboardStats()); }
    catch { message.error('加载统计数据失败'); }
    setLoading(false);
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  return { stats, loading, fetch };
}
