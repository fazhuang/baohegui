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
import { Outlet } from 'react-router-dom';
import {
  ProfileOutlined,
  SearchOutlined,
  BellOutlined,
  UserOutlined,
  LogoutOutlined,
} from '@ant-design/icons';
import { Dropdown, Avatar, Input, Badge, theme as antTheme } from 'antd';
import { usePermission } from '../contexts/PermissionContext';
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

const ShellLayout: React.FC = () => {
  const { user, isAdmin, isSuperAdmin, logout } = usePermission();
  const { token } = antTheme.useToken();
  const isMobile = useIsMobile();

  const userMenuItems = [
    ...(isAdmin ? [
      { key: 'rules', icon: <ProfileOutlined />, label: '规则管理' },
      { key: 'manage', icon: <ProfileOutlined />, label: '系统管理' },
      ...(isSuperAdmin ? [
        { key: 'ops', icon: <ProfileOutlined />, label: '运维中心' },
      ] : []),
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
          <Badge count={3} size="small">
            <BellOutlined style={{ fontSize: 18, cursor: 'pointer', color: token.colorTextSecondary }} />
          </Badge>

          <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
              <Avatar size={32} icon={<UserOutlined />} style={{ backgroundColor: token.colorPrimary }} />
              {!isMobile && (
                <span style={{ fontSize: 13, color: token.colorTextSecondary }}>
                  {user?.username ?? '用户'}
                </span>
              )}
            </div>
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
