/**
 * AuthInitializer — 应用启动时从 token 恢复 session
 *
 * 在 BrowserRouter 内挂载，能访问 history。
 */

import { useEffect } from 'react';
import { useAuthStore } from '../stores/authStore';

const AuthInitializer: React.FC = () => {
  const restoreSession = useAuthStore(s => s.restoreSession);

  useEffect(() => {
    restoreSession();
  }, [restoreSession]);

  return null; // 无 UI
};

export default AuthInitializer;
