import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { ConfigProvider, App as AntApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'

// Layout
import ShellLayout from './layouts/ShellLayout'

// Context
import { PermissionProvider } from './contexts/PermissionContext'

// Auth guard
import RequireRole from './components/RequireRole'

// Pages
import LoginPage from './pages/Login'
import ForgotPassword from './pages/ForgotPassword'
import ResetPassword from './pages/ResetPassword'
import DashboardPage from './pages/Dashboard'
import UploadPage from './pages/Upload'
import ReportPage from './pages/Report'
import HistoryPage from './pages/History'
import AdminRulesPage from './pages/AdminRules'
import AdminPanel from './pages/AdminPanel'

const theme = {
  token: {
    colorPrimary: '#2563eb',
    colorInfo: '#2563eb',
    colorSuccess: '#16a34a',
    colorWarning: '#eab308',
    colorError: '#dc2626',
    colorTextBase: '#334155',
    colorText: '#334155',
    colorTextSecondary: '#64748b',
    colorTextTertiary: '#94a3b8',
    colorBgBase: '#ffffff',
    colorBgContainer: '#ffffff',
    colorBgLayout: '#f1f5f9',
    colorBorder: '#e2e8f0',
    colorBorderSecondary: '#f1f5f9',
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    fontWeightStrong: 600,
    fontSize: 14,
    fontSizeLG: 16,
    fontSizeXL: 20,
    fontSizeHeading1: 24,
    fontSizeHeading2: 20,
    fontSizeHeading3: 16,
    lineHeight: 1.5715,
    borderRadius: 6,
    borderRadiusLG: 8,
    borderRadiusOuter: 12,
    motionDurationSlow: '0.3s',
    motionDurationMid: '0.2s',
    motionDurationFast: '0.1s',
  },
  components: {
    Layout: {
      headerBg: '#ffffff',
      headerColor: '#334155',
      headerHeight: 56,
      siderBg: '#ffffff',
    },
    Menu: {
      darkItemBg: '#1e40af',
      darkItemSelectedBg: 'rgba(255,255,255,0.12)',
      darkItemHoverBg: 'rgba(255,255,255,0.08)',
      darkItemColor: 'rgba(255,255,255,0.75)',
    },
    Card: {
      paddingLG: 24,
    },
    Button: {
      controlHeightLG: 44,
      fontWeight: 500,
    },
    Table: {
      headerBg: '#f8fafc',
      headerColor: '#64748b',
      cellPaddingBlock: 10,
    },
  },
}

function AppRoutes() {
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'))
  const navigate = useNavigate()

  useEffect(() => {
    const checkToken = () => setToken(localStorage.getItem('token'))
    window.addEventListener('storage', checkToken)
    return () => window.removeEventListener('storage', checkToken)
  }, [])

  const isLoggedIn = !!token

  const handleLogin = () => {
    setToken(localStorage.getItem('token'))
    navigate('/', { replace: true })
  }

  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={<LoginPage onLogin={handleLogin} />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />

      {/* Protected */}
      <Route
        element={
          isLoggedIn ? (
            <PermissionProvider>
              <ShellLayout />
            </PermissionProvider>
          ) : (
            <Navigate to="/login" replace />
          )
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="review" element={<UploadPage />} />
        <Route path="review/history" element={<HistoryPage />} />
        <Route path="report/:id" element={<ReportPage />} />

        {/* Rules */}
        <Route path="rules" element={<AdminRulesPage />} />
        <Route path="rules/editor" element={<AdminRulesPage />} />
        <Route path="rules/versions" element={<AdminRulesPage />} />
        <Route path="rules/sync" element={<AdminRulesPage />} />
        <Route path="rules/industry" element={<AdminRulesPage />} />

        {/* Knowledge base — placeholder */}
        <Route path="kg" element={<div style={{ padding: 48, textAlign: 'center' }}>知识图谱 — 即将上线</div>} />
        <Route path="kg/cases" element={<div style={{ padding: 48, textAlign: 'center' }}>案例库 — 即将上线</div>} />
        <Route path="kg/legal" element={<div style={{ padding: 48, textAlign: 'center' }}>法规库 — 即将上线</div>} />

        {/* Reports */}
        <Route path="reports" element={<HistoryPage />} />
        <Route path="reports/feedback" element={<div style={{ padding: 48, textAlign: 'center' }}>反馈管理 — 即将上线</div>} />

        {/* Announcements */}
        <Route path="announcements" element={<div style={{ padding: 48, textAlign: 'center' }}>警示公告 — 即将上线</div>} />
        <Route path="announcements/manage" element={<div style={{ padding: 48, textAlign: 'center' }}>公告管理 — 即将上线</div>} />

        {/* Account */}
        <Route path="account" element={<div style={{ padding: 48, textAlign: 'center' }}>我的账户 — 即将上线</div>} />
        <Route path="account/subscription" element={<div style={{ padding: 48, textAlign: 'center' }}>订阅管理 — 即将上线</div>} />

        {/* System manage — admin+ */}
        <Route element={<RequireRole roles={['super_admin', 'admin']} />}>
          <Route path="manage" element={<AdminPanel />} />
          <Route path="manage/users" element={<AdminPanel />} />
          <Route path="manage/roles" element={<AdminPanel />} />
          <Route path="manage/audit" element={<AdminPanel />} />
          <Route path="manage/quota" element={<AdminPanel />} />
        </Route>

        {/* System manage — super_admin only */}
        <Route element={<RequireRole roles={['super_admin']} />}>
          <Route path="manage/config" element={<AdminPanel />} />
          <Route path="manage/model" element={<AdminPanel />} />
          <Route path="manage/security" element={<AdminPanel />} />
        </Route>

        {/* Ops center — super_admin only */}
        <Route element={<RequireRole roles={['super_admin']} />}>
          <Route path="ops" element={<div style={{ padding: 48, textAlign: 'center' }}>运维中心 — 即将上线</div>} />
          <Route path="ops/scheduler" element={<div style={{ padding: 48, textAlign: 'center' }}>规则同步调度 — 即将上线</div>} />
          <Route path="ops/crawler" element={<div style={{ padding: 48, textAlign: 'center' }}>案例采集引擎 — 即将上线</div>} />
          <Route path="ops/kg-seed" element={<div style={{ padding: 48, textAlign: 'center' }}>知识图谱播种 — 即将上线</div>} />
          <Route path="ops/health" element={<div style={{ padding: 48, textAlign: 'center' }}>系统健康 — 即将上线</div>} />
        </Route>

        {/* Backward-compatible redirects */}
        <Route path="upload" element={<Navigate to="/review" replace />} />
        <Route path="history" element={<Navigate to="/review/history" replace />} />
        <Route path="admin/rules" element={<Navigate to="/rules" replace />} />
        <Route path="admin/panel" element={<Navigate to="/manage" replace />} />
      </Route>

      {/* 404 */}
      <Route path="*" element={<Navigate to={isLoggedIn ? '/' : '/login'} replace />} />
    </Routes>
  )
}

function App() {
  return (
    <ConfigProvider locale={zhCN} theme={theme}>
      <AntApp>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  )
}

export default App
