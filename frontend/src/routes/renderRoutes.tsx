/**
 * renderRoutes — 将 routeConfig 转换为 React Router <Route> 树
 *
 * 这是真实应用路由的唯一生成入口。
 * App.tsx 不再手写业务 <Route>。
 *
 * 功能：
 *   - lazy element + Suspense fallback + ErrorBoundary
 *   - nested children (递归)
 *   - index route
 *   - redirect route (Navigate to)
 *   - RouteGuard 统一套用 (requiredRoles / requiredPermissions)
 *   - 403 返回 (requiredRoles=[] → 需要登录但禁止访问)
 */

import React, { Suspense } from 'react';
import { Route, Navigate } from 'react-router-dom';
import { Spin } from 'antd';
import type { RouteConfig } from './types';
import RouteGuard from './RouteGuard';
import ErrorBoundary from '../components/ErrorBoundary';
import NotFoundPage from './NotFoundPage';

const FB = <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}><Spin size="large" /></div>;

/** ErrorBoundary + Suspense 包裹的懒加载组件 */
function EL({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <Suspense fallback={FB}>{children}</Suspense>
    </ErrorBoundary>
  );
}

/** 将单个 RouteConfig 转换为 <Route> 元素 */
export function renderRoute(route: RouteConfig): React.ReactElement {
  const { path, element: El, index, redirect, requiredRoles, requiredPermissions, children } = route;

  // ── 重定向路由 ──
  if (redirect) {
    return <Route key={path} path={path} element={<Navigate to={redirect} replace />} />;
  }

  // ── 确定该路由的元素 ──
  let node: React.ReactNode;

  if (requiredRoles === undefined) {
    // 公开路由 (无需认证) — 不做 RouteGuard
    node = El ? <EL><El /></EL> : null;
  } else if (requiredRoles.length === 0) {
    // [] = 需要登录但禁止访问 → 403
    node = <RouteGuard roles={[]} />;
  } else {
    // 受保护路由 — RouteGuard 统一套用
    node = (
      <RouteGuard roles={requiredRoles} permissions={requiredPermissions}>
        {El ? <EL><El /></EL> : null}
      </RouteGuard>
    );
  }

  // ── 递归子路由 ──
  const childRoutes = children
    ? children.map(child => renderRoute(child))
    : undefined;

  if (index) {
    return <Route key={path} index element={node} />;
  }

  if (childRoutes && childRoutes.length > 0) {
    return (
      <Route key={`${path}--parent`} path={path} element={node}>
        {childRoutes}
      </Route>
    );
  }

  return <Route key={path} path={path} element={node} />;
}

/** 将 routeConfig[] 转换为 <Route> 元素列表 (不含 404 兜底) */
export function renderRouteTree(configs: RouteConfig[]): React.ReactElement[] {
  return configs.map(renderRoute);
}

/** 将 routeConfig[] 转换为含 404 兜底的 <Route> 元素列表 (用于顶层 <Routes>) */
export function renderRouteTreeWith404(configs: RouteConfig[]): React.ReactElement[] {
  const routes = renderRouteTree(configs);
  routes.push(<Route key="*" path="*" element={<NotFoundPage />} />);
  return routes;
}

export default renderRouteTree;
