/** Admin feature — 审计日志 Tab 状态 hook */

import { useState, useCallback, useEffect } from 'react';
import { listAuditLogs } from '../../../services/api';
import type { AuditLogEntry } from '../../../types/admin-types';

export function useAuditLog() {
  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listAuditLogs({ limit: 200 });
      setLogs(res.logs);
      setTotal(res.total);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  return { logs, total, loading, load };
}
