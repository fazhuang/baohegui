/**
 * App — 应用根组件
 *
 * 路由树由 routeConfig 自动生成, 不再手写 <Route>。
 * 认证状态通过 zustand useAuthStore 统一管理。
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider, App as AntApp, Spin } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useAuthStore } from './stores/authStore'
import ShellLayout from './layouts/ShellLayout'
import { routeConfig } from './routes/routeConfig'
import { renderRouteTree } from './routes/renderRoutes'
import AuthInitializer from './components/AuthInitializer'

const FB = <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}><Spin size="large" /></div>

/** 受保护壳：未认证 → 跳转登录；认证中 → 加载态 */
function ProtectedShell() {
  const user = useAuthStore(s => s.user)
  const loading = useAuthStore(s => s.loading)
  const token = localStorage.getItem('token')
  if (loading) return FB
  if (!token || !user) {
    return <Navigate to="/login" replace />
  }
  return <ShellLayout />
}

const theme = {
  token: {
    colorPrimary: '#2563eb', colorInfo: '#2563eb', colorSuccess: '#16a34a',
    colorWarning: '#eab308', colorError: '#dc2626', colorTextBase: '#334155',
    colorText: '#334155', colorTextSecondary: '#64748b', colorTextTertiary: '#94a3b8',
    colorBgBase: '#ffffff', colorBgContainer: '#ffffff', colorBgLayout: '#f1f5f9',
    colorBorder: '#e2e8f0', colorBorderSecondary: '#f1f5f9',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    fontWeightStrong: 600, fontSize: 14, fontSizeLG: 16, fontSizeXL: 20,
    fontSizeHeading1: 24, fontSizeHeading2: 20, fontSizeHeading3: 16, lineHeight: 1.5715,
    borderRadius: 6, borderRadiusLG: 8, borderRadiusOuter: 12,
    motionDurationSlow: '0.3s', motionDurationMid: '0.2s', motionDurationFast: '0.1s',
  },
  components: {
    Layout: { headerBg: '#ffffff', headerColor: '#334155', headerHeight: 56, siderBg: '#ffffff' },
    Menu: { darkItemBg: '#1e40af', darkItemSelectedBg: 'rgba(255,255,255,0.12)', darkItemHoverBg: 'rgba(255,255,255,0.08)', darkItemColor: 'rgba(255,255,255,0.75)' },
    Card: { paddingLG: 24 },
    Button: { controlHeightLG: 44, fontWeight: 500 },
    Table: { headerBg: '#f8fafc', headerColor: '#64748b', cellPaddingBlock: 10 },
  },
}

function AppInner() {
  return (
    <BrowserRouter>
      <AuthInitializer />
      <Routes>
        {renderRouteTree(routeConfig)}
        {/* 兜底 404 (处理受保护壳外的未知路径) */}
        <Route element={<ProtectedShell />}>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

function App() {
  return (
    <ConfigProvider locale={zhCN} theme={theme}>
      <AntApp>
        <AppInner />
      </AntApp>
    </ConfigProvider>
  )
}

export default App
