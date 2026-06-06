import React, { useState, useEffect } from 'react'
import {
  Layout, Menu, Button, Dropdown, Drawer, Spin, Avatar,
} from 'antd'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import {
  UploadOutlined,
  HistoryOutlined,
  LogoutOutlined,
  MenuOutlined,
  SettingOutlined,
  AppstoreOutlined,
  UserOutlined,
  ProfileOutlined,
} from '@ant-design/icons'
import { getCurrentUser } from '../services/api'

const { Header, Sider, Content } = Layout

function useMobile(): boolean {
  const [mobile, setMobile] = useState(window.innerWidth < 768)
  useEffect(() => {
    const onResize = () => setMobile(window.innerWidth < 768)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return mobile
}

function useIsTablet(): boolean {
  const [tablet, setTablet] = useState(
    window.innerWidth >= 768 && window.innerWidth < 1024,
  )
  useEffect(() => {
    const onResize = () =>
      setTablet(window.innerWidth >= 768 && window.innerWidth < 1024)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return tablet
}

interface AppLayoutProps {
  onLogout?: () => void
}

const AppLayout: React.FC<AppLayoutProps> = ({ onLogout }) => {
  const navigate = useNavigate()
  const location = useLocation()
  const isMobile = useMobile()
  const isTablet = useIsTablet()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [role, setRole] = useState<string | null>(null)
  const [username, setUsername] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const isAdmin = role === 'admin'

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) {
      navigate('/login')
      return
    }
    getCurrentUser()
      .then((user) => {
        setRole(user.role)
        setUsername(user.username)
        localStorage.setItem('role', user.role)
        localStorage.setItem('username', user.username)
      })
      .catch(() => {
        const localRole = localStorage.getItem('role')
        const localUsername = localStorage.getItem('username')
        if (localRole) {
          setRole(localRole)
          setUsername(localUsername || '')
        } else {
          navigate('/login')
        }
      })
      .finally(() => setLoading(false))
  }, [navigate])

  const handleLogout = () => {
    if (onLogout) {
      onLogout()
    } else {
      localStorage.removeItem('token')
      localStorage.removeItem('role')
      localStorage.removeItem('username')
      navigate('/login')
    }
  }

  // ── Sidebar menu items (icon only) ───────────────────
  const sidebarItems = [
    {
      key: '/',
      icon: <AppstoreOutlined style={{ fontSize: 20 }} />,
      label: '工作台',
    },
    {
      key: '/upload',
      icon: <UploadOutlined style={{ fontSize: 20 }} />,
      label: '文件上传',
    },
    {
      key: '/history',
      icon: <HistoryOutlined style={{ fontSize: 20 }} />,
      label: '历史记录',
    },
  ]

  const adminItems = [
    {
      key: '/admin/rules',
      icon: <SettingOutlined style={{ fontSize: 20 }} />,
      label: '规则管理',
    },
    {
      key: '/admin/panel',
      icon: <AppstoreOutlined style={{ fontSize: 20 }} />,
      label: '管理中心',
    },
  ]

  // ── Mobile bottom tab items ──────────────────────────
  const mobileTabItems = [
    { key: '/', icon: <AppstoreOutlined />, label: '工作台' },
    { key: '/upload', icon: <UploadOutlined />, label: '上传' },
    { key: '/history', icon: <HistoryOutlined />, label: '历史' },
    ...(isAdmin
      ? [
          {
            key: '/admin/rules',
            icon: <SettingOutlined />,
            label: '规则',
          },
          {
            key: '/admin/panel',
            icon: <AppstoreOutlined />,
            label: '管理',
          },
        ]
      : []),
  ]

  // ── User dropdown items ──────────────────────────────
  const userMenuItems = [
    ...(isAdmin
      ? [
          {
            key: 'rules',
            icon: <SettingOutlined />,
            label: '规则管理',
            onClick: () => navigate('/admin/rules'),
          },
          {
            key: 'panel',
            icon: <AppstoreOutlined />,
            label: '管理中心',
            onClick: () => navigate('/admin/panel'),
          },
          { type: 'divider' as const },
        ]
      : []),
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      onClick: handleLogout,
    },
  ]

  if (loading) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100vh',
          background: 'var(--color-bg)',
        }}
      >
        <Spin size="large" />
      </div>
    )
  }

  // ── DESKTOP / TABLET LAYOUT ──────────────────────────
  if (!isMobile) {
    return (
      <>
        <style>{`
@media (max-width: 768px) {
  .ant-layout-sider { position: fixed; z-index: 1000; }
  .app-content { padding: 12px; margin-left: 0; }
  .app-header { padding: 0 12px; }
}
`}</style>
        <Layout style={{ minHeight: '100vh' }}>
        {/* Top Brand Bar */}
        <Header
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 20px',
            height: "var(--header-height)",
            lineHeight: "var(--header-height)",
            position: 'sticky',
            top: 0,
            zIndex: 10,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
            }}
          >
            <ProfileOutlined style={{ fontSize: 22, color: '#fff' }} />
            <span
              style={{
                fontSize: 17,
                fontWeight: 600,
                color: '#fff',
                letterSpacing: 1,
              }}
            >
              包合规
            </span>
            <span
              style={{
                fontSize: 11,
                color: 'rgba(255,255,255,0.45)',
                marginLeft: 4,
                letterSpacing: 0.5,
                display: isTablet ? 'none' : 'inline',
              }}
            >
              招标文件合规自检
            </span>
          </div>

          <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                cursor: 'pointer',
                color: 'rgba(255,255,255,0.85)',
              }}
            >
              <Avatar
                size={28}
                icon={<UserOutlined />}
                style={{ backgroundColor: 'rgba(255,255,255,0.15)' }}
              />
              <span
                style={{
                  fontSize: 13,
                  maxWidth: 100,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  display: isTablet ? 'none' : 'inline',
                }}
              >
                {username || '用户'}
              </span>
            </div>
          </Dropdown>
        </Header>

        <Layout hasSider>
          {/* 左侧导航栏 */}
          <Sider
            width={200}
            theme="dark"
            style={{
              position: 'sticky',
              top: "var(--header-height)",
              height: "calc(100vh - var(--header-height))",
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                height: '100%',
              }}
            >
              <Menu
                className="sidebar-nav"
                mode="inline"
                theme="dark"
                selectedKeys={[location.pathname]}
                items={sidebarItems}
                onClick={({ key }) => navigate(key)}
                style={{
                  borderInlineEnd: 'none',
                  marginTop: 8,
                  flex: 1,
                }}
              />
              {isAdmin && (
                <Menu
                  className="sidebar-nav"
                  mode="inline"
                  theme="dark"
                  selectedKeys={[location.pathname]}
                  items={adminItems}
                  onClick={({ key }) => navigate(key)}
                  style={{
                    borderInlineEnd: 'none',
                    marginBottom: 8,
                  }}
                />
              )}
            </div>
          </Sider>

          {/* Content */}
          <Content
            style={{
              padding: 24,
              maxWidth: isTablet ? '100%' : 1200,
              margin: '0 auto',
              width: '100%',
            }}
          >
            <div className="page-fade-in">
              <Outlet />
            </div>
          </Content>
        </Layout>
      </Layout>
      </>
    )
  }

  // ── MOBILE LAYOUT ────────────────────────────────────
  return (
    <Layout style={{ minHeight: '100vh', paddingBottom: 56 }}>
      {/* Mobile Top Bar */}
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 12px',
          height: "var(--header-height-mobile)",
          lineHeight: "var(--header-height-mobile)",
          position: 'sticky',
          top: 0,
          zIndex: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Button
            type="text"
            icon={<MenuOutlined style={{ fontSize: 18, color: '#fff' }} />}
            onClick={() => setDrawerOpen(true)}
          />
          <ProfileOutlined style={{ fontSize: 18, color: '#fff' }} />
          <span
            style={{ fontSize: 15, fontWeight: 600, color: '#fff' }}
          >
            包合规
          </span>
        </div>

        <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
          <Avatar
            size={28}
            icon={<UserOutlined />}
            style={{
              backgroundColor: 'rgba(255,255,255,0.15)',
              cursor: 'pointer',
            }}
          />
        </Dropdown>
      </Header>

      {/* Mobile Drawer */}
      <Drawer
        title={
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <ProfileOutlined style={{ color: 'var(--color-brand)' }} />
            <span style={{ color: 'var(--color-brand)', fontWeight: 600 }}>
              包合规
            </span>
          </span>
        }
        placement="left"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={240}
        styles={{ body: { padding: 0 } }}
      >
        <Menu
          mode="vertical"
          selectedKeys={[location.pathname]}
          items={[...sidebarItems, ...(isAdmin ? adminItems : [])]}
          onClick={({ key }) => {
            navigate(key)
            setDrawerOpen(false)
          }}
          style={{ borderInlineEnd: 'none' }}
        />
      </Drawer>

      {/* Content */}
      <Content style={{ padding: '12px', width: '100%' }}>
        <div className="page-fade-in">
          <Outlet />
        </div>
      </Content>

      {/* Bottom Tab Bar */}
      <div className="bottom-tab-bar">
        {mobileTabItems.map((item) => {
          const isActive = location.pathname === item.key
          return (
            <div
              key={item.key}
              onClick={() => navigate(item.key)}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 2,
                padding: '4px 12px',
                cursor: 'pointer',
                color: isActive
                  ? 'var(--color-action)'
                  : 'var(--color-text-tertiary)',
                transition: 'color 0.2s',
                fontSize: 13,
                minWidth: 56,
              }}
            >
              <span style={{ fontSize: 20 }}>{item.icon}</span>
              <span style={{ fontSize: 10, fontWeight: isActive ? 600 : 400 }}>
                {item.label}
              </span>
            </div>
          )
        })}
      </div>
    </Layout>
  )
}

export default AppLayout
