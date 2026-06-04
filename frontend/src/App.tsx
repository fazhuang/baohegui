import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { ConfigProvider, App as AntApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import AppLayout from './components/AppLayout'
import UploadPage from './pages/Upload'
import ReportPage from './pages/Report'
import HistoryPage from './pages/History'
import LoginPage from './pages/Login'
import DashboardPage from './pages/Dashboard'
import AdminRulesPage from './pages/AdminRules'
import AdminPanel from './pages/AdminPanel'

const theme = {
  token: {
    // ── Brand & Action ──
    colorPrimary: '#2563eb',
    colorInfo: '#2563eb',
    colorSuccess: '#16a34a',
    colorWarning: '#eab308',
    colorError: '#dc2626',

    // ── Text ──
    colorTextBase: '#334155',
    colorText: '#334155',
    colorTextSecondary: '#64748b',
    colorTextTertiary: '#94a3b8',

    // ── Surfaces ──
    colorBgBase: '#ffffff',
    colorBgContainer: '#ffffff',
    colorBgLayout: '#f1f5f9',
    colorBorder: '#e2e8f0',
    colorBorderSecondary: '#f1f5f9',

    // ── Typography ──
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

    // ── Radius ──
    borderRadius: 6,
    borderRadiusLG: 8,
    borderRadiusOuter: 12,

    // ── Motion ──
    motionDurationSlow: '0.3s',
    motionDurationMid: '0.2s',
    motionDurationFast: '0.1s',
  },
  components: {
    Layout: {
      headerBg: '#1e40af',
      headerColor: '#ffffff',
      headerHeight: 56,
      siderBg: '#1e40af',
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

  // 监听 localStorage 变化（跨标签页）
  useEffect(() => {
    const checkToken = () => setToken(localStorage.getItem('token'))
    window.addEventListener('storage', checkToken)
    return () => window.removeEventListener('storage', checkToken)
  }, [])

  const isLoggedIn = !!token

  return (
    <Routes>
      <Route path="/login" element={
        <LoginPage onLogin={() => {
          setToken(localStorage.getItem('token'))
          navigate('/', { replace: true })
        }} />
      } />
      <Route path="/" element={isLoggedIn ? <AppLayout onLogout={() => {
        localStorage.removeItem('token')
        localStorage.removeItem('role')
        localStorage.removeItem('username')
        setToken(null)
        navigate('/login', { replace: true })
      }} /> : <Navigate to="/login" replace />}>
        <Route index element={<DashboardPage />} />
        <Route path="upload" element={<UploadPage />} />
        <Route path="report/:id" element={<ReportPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="admin/rules" element={<AdminRulesPage />} />
        <Route path="admin/panel" element={<AdminPanel />} />
      </Route>
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
