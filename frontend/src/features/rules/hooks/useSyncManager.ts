/** Rules feature — 同步管理 Tab 状态 hook */

import { useState, useCallback, useEffect } from 'react';
import { message } from 'antd';
import { getSyncStatus, getSyncHistory, runSync } from '../../../services/api';
import type { SyncStatus, SyncHistoryItem, SyncResultData } from '../../../types';
import { getErrorMessage } from '../../../utils/error';

export function useSyncManager() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [history, setHistory] = useState<SyncHistoryItem[]>([]);
  const [syncing, setSyncing] = useState(false);

  const loadSyncStatus = useCallback(async () => {
    try {
      setStatus(await getSyncStatus());
      setHistory(await getSyncHistory());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadSyncStatus(); }, [loadSyncStatus]);

  const handleSync = async (platform: string) => {
    setSyncing(true);
    try {
      const result: SyncResultData = await runSync(platform);
      message.success(`同步完成：新增${result.new_rules} 更新${result.updated_rules}`);
      loadSyncStatus();
    } catch (e: unknown) {
      message.error(getErrorMessage(e, '同步失败'));
    }
    setSyncing(false);
  };

  return { status, history, syncing, loadSyncStatus, handleSync };
}
