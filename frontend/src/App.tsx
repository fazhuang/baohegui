import React, { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider, App as AntApp, Spin } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { PermissionProvider, usePermission } from './contexts/PermissionContext'
import ShellLayout from './layouts/ShellLayout'
import RouteGuard from './routes/RouteGuard'
import NotFoundPage from './routes/NotFoundPage'
import ComingSoonPage from './components/common/ComingSoonPage'
import ErrorBoundary from './components/ErrorBoundary'

// ── 懒加载页面 ──────────────────────────────────────────────
const LoginPage = lazy(() => import('./pages/Login'))
const ForgotPassword = lazy(() => import('./pages/ForgotPassword'))
const ResetPassword = lazy(() => import('./pages/ResetPassword'))
const DashboardPage = lazy(() => import('./pages/Dashboard'))
const UploadPage = lazy(() => import('./pages/Upload'))
const ReportPage = lazy(() => import('./pages/Report'))
const HistoryPage = lazy(() => import('./pages/History'))
const AdminRulesPage = lazy(() => import('./pages/AdminRules'))
const AdminPanel = lazy(() => import('./pages/AdminPanel'))
const ReviewCenter = lazy(() => import('./pages/ReviewCenter'))
const RulesCenter = lazy(() => import('./pages/RulesCenter'))
const KnowledgeBase = lazy(() => import('./pages/KnowledgeBase'))
const ReportCenter = lazy(() => import('./pages/ReportCenter'))
const Announcements = lazy(() => import('./pages/Announcements'))
const UserCenter = lazy(() => import('./pages/UserCenter'))
const SystemManage = lazy(() => import('./pages/SystemManage'))

const FB = <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}><Spin size="large" /></div>

/** ErrorBoundary 包裹的懒加载组件 */
function EL({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <Suspense fallback={FB}>{children}</Suspense>
    </ErrorBoundary>
  )
}

function ProtectedShell() {
  const { user, loading } = usePermission()
  const token = localStorage.getItem('token')
  if (loading) return FB
  if (!token || !user) return <Navigate to="/login" replace />
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

function App() {
  return (
    <ConfigProvider locale={zhCN} theme={theme}>
      <AntApp>
        <BrowserRouter>
          <Routes>
            {/* ── 公开路由 ────────────────────────────────── */}
            <Route path="/login" element={<EL><LoginPage onLogin={() => window.location.href = '/'} /></EL>} />
            <Route path="/forgot-password" element={<EL><ForgotPassword /></EL>} />
            <Route path="/reset-password" element={<EL><ResetPassword /></EL>} />

            {/* ── 受保护路由 ──────────────────────────────── */}
            <Route element={<PermissionProvider><ProtectedShell /></PermissionProvider>}>
              {/* 工作台 */}
              <Route index element={<EL><DashboardPage /></EL>} />
              <Route path="report/:id" element={<EL><ReportPage /></EL>} />

              {/* ── 审查中心 ──────────────────────────────── */}
              <Route path="review" element={<EL><ReviewCenter /></EL>}>
                <Route index element={<EL><UploadPage /></EL>} />
                <Route path="history" element={<EL><HistoryPage /></EL>} />
              </Route>

              {/* ── 报告中心 ──────────────────────────────── */}
              <Route path="reports" element={<EL><ReportCenter /></EL>}>
                <Route index element={<EL><HistoryPage /></EL>} />
                <Route path="feedback" element={
                  <RouteGuard roles={['admin']}><ComingSoonPage title="反馈管理" /></RouteGuard>
                } />
              </Route>

              {/* ── 知识库 ────────────────────────────────── */}
              <Route path="kg" element={<EL><KnowledgeBase /></EL>}>
                <Route index element={<ComingSoonPage title="知识图谱" />} />
                <Route path="cases" element={<ComingSoonPage title="案例库" />} />
                <Route path="legal" element={<ComingSoonPage title="法规库" />} />
              </Route>

              {/* ── 警示公告 ──────────────────────────────── */}
              <Route path="announcements" element={<EL><Announcements /></EL>}>
                <Route index element={<ComingSoonPage title="警示公告" />} />
                <Route path="manage" element={
                  <RouteGuard roles={['admin']}><ComingSoonPage title="公告管理" /></RouteGuard>
                } />
              </Route>

              {/* ── 用户中心 ──────────────────────────────── */}
              <Route path="account" element={<EL><UserCenter /></EL>}>
                <Route index element={<ComingSoonPage title="我的账户" />} />
                <Route path="subscription" element={<ComingSoonPage title="订阅管理" />} />
              </Route>

              {/* ── 规则中心 (admin) ──────────────────────── */}
              <Route element={<RouteGuard roles={['admin']} />}>
                <Route path="rules" element={<EL><RulesCenter /></EL>}>
                  <Route index element={<EL><AdminRulesPage /></EL>} />
                  <Route path="editor" element={<EL><AdminRulesPage /></EL>} />
                  <Route path="versions" element={<EL><AdminRulesPage /></EL>} />
                  <Route path="sync" element={<EL><AdminRulesPage /></EL>} />
                  <Route path="industry" element={<ComingSoonPage title="行业配置" />} />
                </Route>

                {/* ── 系统管理 (admin) ─────────────────── */}
                <Route path="manage" element={<EL><SystemManage /></EL>}>
                  <Route index element={<EL><AdminPanel /></EL>} />
                  <Route path="audit" element={<EL><AdminPanel /></EL>} />
                  <Route path="quota" element={<EL><AdminPanel /></EL>} />
                </Route>
              </Route>

              {/* ── 向后兼容重定向 ────────────────────────── */}
              <Route path="upload" element={<Navigate to="/review" replace />} />
              <Route path="history" element={<Navigate to="/review/history" replace />} />
              <Route path="admin/rules" element={<Navigate to="/rules" replace />} />
              <Route path="admin/panel" element={<Navigate to="/manage" replace />} />

              {/* ── 404 ───────────────────────────────────── */}
              <Route path="*" element={<NotFoundPage />} />
            </Route>

            {/* 最外层 404 */}
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  )
}

export default App
