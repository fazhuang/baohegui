/**
 * ShellLayout — 顶层布局壳
 *
 * 提供：
 *   - 顶部 Header（Logo + 搜索 + 通知 + 用户菜单）
 *   - 左侧 Sider（包含 Sidebar 分组导航）
 *   - 内容区 <Outlet />
 *   - 底部状态栏
 *
 * 不包含权限逻辑，仅负责 UI 壳。
 */

import React from 'react';
import { Layout } from 'antd';
import { Outlet, useNavigate } from 'react-router-dom';
import {
  ProfileOutlined,
  SearchOutlined,
  BellOutlined,
  UserOutlined,
  LogoutOutlined,
} from '@ant-design/icons';
import { Dropdown, Avatar, Input, Badge, theme as antTheme } from 'antd';
import { useAuthStore } from '../stores/authStore';
import Sidebar from './Sidebar';
import MobileNav from './MobileNav';

const { Header, Sider, Content, Footer } = Layout;

/** 移动端检测 hook */
function useIsMobile(): boolean {
  const [m, setM] = React.useState(window.innerWidth < 768);
  React.useEffect(() => {
    const on = () => setM(window.innerWidth < 768);
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  return m;
}

const ShellLayout: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
  const user = useAuthStore(s => s.user);
  const isAdmin = useAuthStore(s => s.isAdmin());
  const logout = useAuthStore(s => s.logout);
  const navigate = useNavigate();
  const { token } = antTheme.useToken();
  const isMobile = useIsMobile();
  const [notificationOpen, setNotificationOpen] = React.useState(false);

  const notifications = [
    { key: 'platform-rules', title: '平台规则有更新', description: '查看最新公共资源交易平台审查提醒', path: '/announcements' },
    { key: 'report-review', title: '待复核报告 1 份', description: '进入报告中心查看最近审查结果', path: '/reports' },
    { key: 'legal-update', title: '法规库新增条目', description: '查看法规库与合规依据更新', path: '/kg/legal' },
  ];

  const userMenuItems = [
    ...(isAdmin ? [
      { key: 'rules', icon: <ProfileOutlined />, label: '规则管理' },
      { key: 'manage', icon: <ProfileOutlined />, label: '系统管理' },
      { type: 'divider' as const },
    ] : []),
    {
      key: 'account',
      icon: <UserOutlined />,
      label: '我的账户',
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      danger: true,
      onClick: logout,
    },
  ];

  const handleUserMenuClick = ({ key }: { key: string }) => {
    if (key === 'logout') {
      logout();
      return;
    }

    const routeByKey: Record<string, string> = {
      rules: '/rules',
      manage: '/manage',
      account: '/account',
    };
    const path = routeByKey[key];
    if (path) navigate(path);
  };

  const notificationMenuItems = notifications.map(item => ({
    key: item.key,
    label: (
      <div style={{ width: isMobile ? 240 : 300, padding: '4px 0' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: token.colorText }}>{item.title}</div>
        <div style={{ marginTop: 2, fontSize: 12, color: token.colorTextSecondary, whiteSpace: 'normal' as const }}>
          {item.description}
        </div>
      </div>
    ),
  }));

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* ── Top Bar ── */}
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: isMobile ? '0 12px' : '0 24px',
          height: 56,
          lineHeight: '56px',
          position: 'sticky',
          top: 0,
          zIndex: 100,
          background: token.colorBgContainer,
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        {/* 左侧：Logo + 产品名 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <ProfileOutlined style={{ fontSize: 22, color: token.colorPrimary }} />
          <span style={{ fontSize: 17, fontWeight: 700, color: token.colorText }}>
            包合规
          </span>
          {!isMobile && (
            <span style={{ fontSize: 11, color: token.colorTextTertiary, marginLeft: 4 }}>
              招标文件合规自检
            </span>
          )}
        </div>

        {/* 中间：全局搜索 (placeholder) */}
        {!isMobile && (
          <Input
            prefix={<SearchOutlined style={{ color: token.colorTextQuaternary }} />}
            placeholder="搜索文件、规则、用户... (⌘K)"
            style={{
              maxWidth: 400,
              borderRadius: 8,
              background: token.colorFillSecondary,
              border: 'none',
            }}
            readOnly
          />
        )}

        {/* 右侧：通知 + 用户 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <Dropdown
            menu={{
              items: notificationMenuItems,
              onClick: ({ key }) => {
                const target = notifications.find(item => item.key === key);
                if (!target) return;
                setNotificationOpen(false);
                navigate(target.path);
              },
            }}
            trigger={['click']}
            open={notificationOpen}
            onOpenChange={setNotificationOpen}
            placement="bottomRight"
          >
            <button
              type="button"
              aria-label="系统通知"
              style={{
                border: 'none',
                background: 'transparent',
                padding: 0,
                lineHeight: 1,
                cursor: 'pointer',
              }}
            >
              <Badge count={notifications.length} size="small">
                <BellOutlined style={{ fontSize: 18, color: token.colorTextSecondary }} />
              </Badge>
            </button>
          </Dropdown>

          <Dropdown menu={{ items: userMenuItems, onClick: handleUserMenuClick }} placement="bottomRight" trigger={['click']}>
            <button
              type="button"
              aria-label="用户菜单"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                cursor: 'pointer',
                border: 'none',
                background: 'transparent',
                padding: 0,
              }}
            >
              <Avatar size={32} icon={<UserOutlined />} style={{ backgroundColor: token.colorPrimary }} />
              {!isMobile && (
                <span style={{ fontSize: 13, color: token.colorTextSecondary }}>
                  {user?.username ?? '用户'}
                </span>
              )}
            </button>
          </Dropdown>
        </div>
      </Header>

      {/* ── Body ── */}
      <Layout hasSider>
        {!isMobile && (
          <Sider
            width={200}
            style={{
              background: token.colorBgContainer,
              borderRight: `1px solid ${token.colorBorderSecondary}`,
              position: 'sticky',
              top: 56,
              height: 'calc(100vh - 56px)',
              overflow: 'auto',
            }}
          >
            <Sidebar />
          </Sider>
        )}

        <Content style={{ padding: isMobile ? 12 : 24, minHeight: 'calc(100vh - 56px - 32px)' }}>
          <Outlet />
          {children}
        </Content>
      </Layout>

      {/* ── Footer ── */}
      <Footer style={{
        textAlign: 'center',
        padding: '8px 24px',
        fontSize: 12,
        color: token.colorTextTertiary,
        borderTop: `1px solid ${token.colorBorderSecondary}`,
      }}>
        包合规 v2.0 · {new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
      </Footer>

      {/* ── Mobile Bottom Tab Bar ── */}
      {isMobile && <MobileNav />}
    </Layout>
  );
};

export default ShellLayout;
