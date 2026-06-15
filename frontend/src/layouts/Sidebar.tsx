import React from 'react';
import { Menu } from 'antd';
import { useNavigate, useLocation } from 'react-router-dom';
import { usePermission } from '../contexts/PermissionContext';
import { MENU_GROUPS, getVisibleItems } from '../config/menu';
import { theme as antTheme } from 'antd';

const Sidebar: React.FC = () => {
  const { user, role } = usePermission();
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = antTheme.useToken();

  if (!role || !user) return null;

  const visibleGroups = MENU_GROUPS
    .filter(g => g.visibleTo.includes(role))
    .sort((a, b) => a.order - b.order);

  const menuItems = visibleGroups.map(group => {
    const children = getVisibleItems(group.key, role)
      .map(item => ({
        key: item.path,
        label: (
          <span style={{ fontSize: 13 }}>
            {item.label}
            {item.adminOnly && <span style={{ fontSize: 10, color: token.colorTextQuaternary, marginLeft: 4 }}>(管理)</span>}
          </span>
        ),
      }));

    return {
      type: 'group' as const,
      key: group.key,
      label: (
        <span style={{
          display: 'flex', alignItems: 'center', gap: 8, fontSize: 11,
          fontWeight: 600, color: token.colorTextQuaternary,
          textTransform: 'uppercase' as const, letterSpacing: '0.5px', paddingLeft: 4,
        }}>
          {group.label}
        </span>
      ),
      children: children.length > 0 ? children : undefined,
    };
  });

  return (
    <Menu
      mode="inline"
      selectedKeys={[location.pathname]}
      items={menuItems}
      onClick={({ key }) => navigate(key)}
      style={{ borderInlineEnd: 'none', paddingTop: 8, paddingBottom: 8, background: token.colorBgContainer, height: '100%' }}
    />
  );
};

export default Sidebar;
