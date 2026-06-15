/**
 * Sidebar — 分层分组导航
 *
 * 显示 9 个一级分组，每组下含二级菜单项。
 * 根据当前用户角色动态隐藏无权限的分组和菜单项。
 * 当前选中菜单项通过 React Router location 判定。
 */

import React from 'react';
import { Menu, Typography } from 'antd';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  AppstoreOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  BookOutlined,
  FileTextOutlined,
  AlertOutlined,
  UserOutlined,
  ControlOutlined,
  DashboardOutlined,
  UploadOutlined,
  HistoryOutlined,
  EyeOutlined,
  EditOutlined,
  BranchesOutlined,
  SyncOutlined,
  ApartmentOutlined,
  NodeIndexOutlined,
  FolderOpenOutlined,
  ReadOutlined,
  UnorderedListOutlined,
  MessageOutlined,
  NotificationOutlined,
  FormOutlined,
  IdcardOutlined,
  DollarOutlined,
  TeamOutlined,
  SafetyOutlined,
  AuditOutlined,
  PieChartOutlined,
  ToolOutlined,
  RobotOutlined,
  LockOutlined,
  ClockCircleOutlined,
  GlobalOutlined,
  ThunderboltOutlined,
  HeartOutlined,
} from '@ant-design/icons';
import { usePermission } from '../contexts/PermissionContext';
import { MENU_GROUPS, getVisibleItems } from '../config/menu';
import { theme as antTheme } from 'antd';

const { Text } = Typography;

/** 字符串 → Ant Design 图标组件映射 */
const ICON_MAP: Record<string, React.ReactNode> = {
  AppstoreOutlined: <AppstoreOutlined />,
  SafetyCertificateOutlined: <SafetyCertificateOutlined />,
  SettingOutlined: <SettingOutlined />,
  BookOutlined: <BookOutlined />,
  FileTextOutlined: <FileTextOutlined />,
  AlertOutlined: <AlertOutlined />,
  UserOutlined: <UserOutlined />,
  ControlOutlined: <ControlOutlined />,
  DashboardOutlined: <DashboardOutlined />,
  UploadOutlined: <UploadOutlined />,
  HistoryOutlined: <HistoryOutlined />,
  EyeOutlined: <EyeOutlined />,
  EditOutlined: <EditOutlined />,
  BranchesOutlined: <BranchesOutlined />,
  SyncOutlined: <SyncOutlined />,
  ApartmentOutlined: <ApartmentOutlined />,
  NodeIndexOutlined: <NodeIndexOutlined />,
  FolderOpenOutlined: <FolderOpenOutlined />,
  ReadOutlined: <ReadOutlined />,
  UnorderedListOutlined: <UnorderedListOutlined />,
  MessageOutlined: <MessageOutlined />,
  NotificationOutlined: <NotificationOutlined />,
  FormOutlined: <FormOutlined />,
  IdcardOutlined: <IdcardOutlined />,
  DollarOutlined: <DollarOutlined />,
  TeamOutlined: <TeamOutlined />,
  SafetyOutlined: <SafetyOutlined />,
  AuditOutlined: <AuditOutlined />,
  PieChartOutlined: <PieChartOutlined />,
  ToolOutlined: <ToolOutlined />,
  RobotOutlined: <RobotOutlined />,
  LockOutlined: <LockOutlined />,
  ClockCircleOutlined: <ClockCircleOutlined />,
  GlobalOutlined: <GlobalOutlined />,
  ThunderboltOutlined: <ThunderboltOutlined />,
  HeartOutlined: <HeartOutlined />,
};

const Sidebar: React.FC = () => {
  const { user, role } = usePermission();
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = antTheme.useToken();

  if (!role || !user) return null;

  const visibleGroups = MENU_GROUPS
    .filter(g => g.visibleTo.includes(role))
    .sort((a, b) => a.order - b.order);

  // 构建 Menu items — 分组为 SubMenu type: 'group'
  const menuItems = visibleGroups.map(group => {
    const children = getVisibleItems(group.key, role).map(item => ({
      key: item.path,
      icon: ICON_MAP[item.icon] || null,
      label: (
        <span style={{ fontSize: 13 }}>
          {item.label}
          {item.adminOnly && (
            <Text type="secondary" style={{ fontSize: 10, marginLeft: 4 }}>
              (管理)
            </Text>
          )}
        </span>
      ),
    }));

    return {
      type: 'group' as const,
      key: group.key,
      label: (
        <span style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: 11,
          fontWeight: 600,
          color: token.colorTextQuaternary,
          textTransform: 'uppercase' as const,
          letterSpacing: '0.5px',
          paddingLeft: 4,
        }}>
          {ICON_MAP[group.icon]}
          {group.label}
        </span>
      ),
      children: children.length > 0 ? children : undefined,
    };
  });

  // 确定当前选中的菜单项
  const selectedKeys = [location.pathname];

  return (
    <Menu
      mode="inline"
      selectedKeys={selectedKeys}
      items={menuItems}
      onClick={({ key }) => navigate(key)}
      style={{
        borderInlineEnd: 'none',
        paddingTop: 8,
        paddingBottom: 8,
        background: token.colorBgContainer,
        height: '100%',
      }}
    />
  );
};

export default Sidebar;
