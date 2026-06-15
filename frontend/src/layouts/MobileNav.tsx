/**
 * MobileNav — 移动端底部 Tab 栏
 *
 * 显示 4-5 个核心入口（工作台、审查、历史、账户，管理员额外显示管理）。
 * 当前页面高亮。
 */

import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  AppstoreOutlined,
  UploadOutlined,
  HistoryOutlined,
  UserOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { usePermission } from '../contexts/PermissionContext';

const MobileNav: React.FC = () => {
  const { isAdmin } = usePermission();
  const navigate = useNavigate();
  const location = useLocation();

  const icons = [
    { key: '/', icon: <AppstoreOutlined />, label: '工作台' },
    { key: '/review', icon: <UploadOutlined />, label: '审查' },
    { key: '/review/history', icon: <HistoryOutlined />, label: '历史' },
    ...(isAdmin ? [
      { key: '/rules', icon: <SettingOutlined />, label: '规则' },
    ] : []),
    { key: '/account', icon: <UserOutlined />, label: '我的' },
  ];

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 100,
        height: 56,
        background: '#fff',
        borderTop: '1px solid #f0f0f0',
        display: 'flex',
        justifyContent: 'space-around',
        alignItems: 'center',
        padding: '4px 8px',
        paddingBottom: 'env(safe-area-inset-bottom, 8px)',
      }}
    >
      {icons.map(item => {
        const isActive = location.pathname === item.key
          || (item.key !== '/' && location.pathname.startsWith(item.key));
        return (
          <div
            key={item.key}
            onClick={() => navigate(item.key)}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 2,
              cursor: 'pointer',
              color: isActive ? '#1677ff' : '#94a3b8',
              fontSize: 11,
              minWidth: 56,
            }}
          >
            <span style={{ fontSize: 22 }}>{item.icon}</span>
            <span style={{ fontWeight: isActive ? 600 : 400 }}>{item.label}</span>
          </div>
        );
      })}
    </div>
  );
};

export default MobileNav;
