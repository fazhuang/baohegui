/**
 * AppRoutes — 应用路由树 (可独立测试)
 *
 * 从 App.tsx 拆出，导出：
 *   - AppRoutes: 可传 skipAuthInit 跳过 AuthInitializer（测试用）
 *   - BrowserAppRoutes: 生产用 (BrowserRouter)
 *
 * 路由分层：
 *   1. 公开路由 — 不进入 ShellLayout (login, forgot-pw, reset-pw)
 *   2. 受保护路由 — 由 ProtectedShell 包裹，未登录跳转 /login
 *   3. 受保护路由内部 — 所有业务页面经 ShellLayout(Sidebar+Header+Outlet) 渲染
 *   4. 受保护 404 — 已登录用户访问未知路径，在 ShellLayout 内显示 NotFoundPage
 */

import { BrowserRouter, Routes, Route, Navigate, MemoryRouter } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';
import ShellLayout from '../layouts/ShellLayout';
import NotFoundPage from './NotFoundPage';
import { routeConfig } from './routeConfig';
import { renderRouteTree } from './renderRoutes';
import AuthInitializer from '../components/AuthInitializer';
import { Spin } from 'antd';

const FB = <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}><Spin size="large" /></div>;

/** 分离公开和受保护路由配置 */
function partitionConfig(configs: typeof routeConfig) {
  const publicRoutes: typeof configs = [];
  const protectedRoutes: typeof configs = [];
  for (const r of configs) {
    if (r.requiredRoles === undefined) {
      publicRoutes.push(r);
    } else {
      protectedRoutes.push(r);
    }
  }
  return { publicRoutes, protectedRoutes };
}

/** 受保护壳：未认证 → 跳转登录；认证中 → 加载态；已认证 → ShellLayout + Outlet */
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

  const { publicRoutes, protectedRoutes } = partitionConfig(routeConfig);

  return (
    <Router {...routerProps}>
      {!skipAuthInit && <AuthInitializer />}
      <Routes>
        {/* 公开路由 — 不进入 ShellLayout */}
        {renderRouteTree(publicRoutes)}

        {/* 受保护路由 — 统一包裹在 ProtectedShell (即 ShellLayout) 下 */}
        <Route element={<ProtectedShell />}>
          {renderRouteTree(protectedRoutes)}
          {/* 受保护 404 — 已登录用户在 ShellLayout 内看到 NotFoundPage */}
          <Route path="*" element={<NotFoundPage />} />
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
