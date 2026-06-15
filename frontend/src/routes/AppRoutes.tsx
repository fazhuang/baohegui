/**
 * AppRoutes — 应用路由树 (可独立测试)
 *
 * 从 App.tsx 拆出，导出：
 *   - AppRoutes: 可传 skipAuthInit 跳过 AuthInitializer（测试用）
 *   - BrowserAppRoutes: 生产用 (BrowserRouter)
 */

import { BrowserRouter, Routes, Route, Navigate, MemoryRouter } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';
import ShellLayout from '../layouts/ShellLayout';
import { routeConfig } from './routeConfig';
import { renderRouteTree } from './renderRoutes';
import AuthInitializer from '../components/AuthInitializer';
import { Spin } from 'antd';

const FB = <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}><Spin size="large" /></div>;

/** 受保护壳：未认证 → 跳转登录；认证中 → 加载态 */
export function ProtectedShell() {
  const user = useAuthStore(s => s.user);
  const loading = useAuthStore(s => s.loading);
  const token = localStorage.getItem('token');
  if (loading) return FB;
  if (!token || !user) {
    return <Navigate to="/login" replace />;
  }
  return <ShellLayout />;
}

interface AppRoutesProps {
  initialPath?: string;
  useMemoryRouter?: boolean;
  /** 跳过 AuthInitializer — 测试用，因为 authStore 已在 beforeEach 预设好了 */
  skipAuthInit?: boolean;
}

/**
 * AppRoutes — 应用路由核心。
 * 测试: useMemoryRouter=true, skipAuthInit=true, initialPath 指定 URL。
 * 生产: 使用 BrowserAppRoutes (BrowserRouter + AuthInitializer)。
 */
export function AppRoutes({ initialPath, useMemoryRouter, skipAuthInit }: AppRoutesProps = {}) {
  const Router = useMemoryRouter ? MemoryRouter : BrowserRouter;
  const routerProps = useMemoryRouter && initialPath
    ? { initialEntries: [initialPath] }
    : {};

  return (
    <Router {...routerProps}>
      {!skipAuthInit && <AuthInitializer />}
      <Routes>
        {renderRouteTree(routeConfig)}
        <Route element={<ProtectedShell />}>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Router>
  );
}

/** BrowserAppRoutes — 生产环境用 (BrowserRouter + AuthInitializer) */
export function BrowserAppRoutes() {
  return <AppRoutes />;
}

export default AppRoutes;
