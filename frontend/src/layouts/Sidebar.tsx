/**
 * Sidebar — 分组导航菜单
 *
 * 菜单数据源：routeConfig (通过 extractMenuItems 派生，再注入 menuStore)
 * 权限控制：useAuthStore.isAdmin / isSuperAdmin
 * 不再依赖 config/menu.tsx。
 */

import React, { useMemo } from 'react';
import { Menu } from 'antd';
import { useNavigate, useLocation } from 'react-router-dom';
import { theme as antTheme } from 'antd';
import { extractMenuItems, type ExtractedMenuItem } from '../routes/routeConfig';
import { routeConfig } from '../routes/routeConfig';
import { useAuthStore } from '../stores/authStore';

const GROUPS: Record<string, { key: string; label: string; order: number }> = {
  workspace:     { key: 'workspace', label: '工作台', order: 10 },
  review:        { key: 'review', label: '审查中心', order: 20 },
  rules:         { key: 'rules', label: '规则中心', order: 30 },
  knowledge:     { key: 'knowledge', label: '知识库', order: 40 },
  reports:       { key: 'reports', label: '报告中心', order: 50 },
  announcements: { key: 'announcements', label: '警示公告', order: 60 },
  account:       { key: 'account', label: '用户中心', order: 70 },
  system:        { key: 'system', label: '系统管理', order: 80 },
  ops:           { key: 'ops', label: '运维中心', order: 90 },
};

/** 从 routeConfig 派生全量菜单项（一次性计算，不在组件内） */
const ALL_MENU_ITEMS: ExtractedMenuItem[] = extractMenuItems(routeConfig);

const Sidebar: React.FC = () => {
  const user = useAuthStore(state => state.user);
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = antTheme.useToken();

  const role = user?.role ?? null;

  const menuItems = useMemo(() => {
    if (!role) return [];

    // 过滤当前角色可见的菜单项
    const visibleItems = ALL_MENU_ITEMS.filter(item => item.requiredRoles.includes(role));

    // 按分组聚合
    const grouped = new Map<string, ExtractedMenuItem[]>();
    for (const item of visibleItems) {
      const list = grouped.get(item.group) || [];
      list.push(item);
      grouped.set(item.group, list);
    }

    // 构建 Menu 的 items 树
    return Array.from(grouped.entries())
      .map(([groupKey, items]) => {
        const group = GROUPS[groupKey];
        if (!group) return null;
        return {
          type: 'group' as const,
          key: groupKey,
          label: (
            <span style={{
              display: 'flex', alignItems: 'center', gap: 8, fontSize: 11,
              fontWeight: 600, color: token.colorTextQuaternary,
              textTransform: 'uppercase' as const, letterSpacing: '0.5px', paddingLeft: 4,
            }}>
              {group.label}
            </span>
          ),
          children: items.map(item => ({
            key: item.path,
            label: (
              <span style={{ fontSize: 13 }}>
                {item.label}
                {item.adminOnly && <span style={{ fontSize: 10, color: token.colorTextQuaternary, marginLeft: 4 }}>(管理)</span>}
              </span>
            ),
          })),
        };
      })
      .filter(Boolean);
  }, [role, token.colorTextQuaternary]);

  if (!user) return null;

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
