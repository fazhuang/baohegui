/**
 * Menu Store — 菜单状态 (派生自 routeConfig)
 *
 * 菜单从 routeConfig 统一生成，不允许单独维护菜单列表。
 */

import { create } from 'zustand';
import type { UserRole } from '../types';

export interface MenuItemData {
  key: string;
  label: string;
  path: string;
  icon: string;
  group: string;
  adminOnly?: boolean;
  visibleTo: UserRole[];
}

export interface MenuGroupData {
  key: string;
  label: string;
  icon: string;
  order: number;
}

interface MenuState {
  items: MenuItemData[];
  groups: MenuGroupData[];
  setItems: (items: MenuItemData[]) => void;
  setGroups: (groups: MenuGroupData[]) => void;
  /** 按 role 获取可见菜单组 */
  getVisibleGroups: (role: UserRole | null) => MenuGroupData[];
  /** 按 role + group 获取可见菜单项 */
  getVisibleItems: (groupKey: string, role: UserRole | null) => MenuItemData[];
}

/** 菜单分组定义 */
const MENU_GROUP_MAP: Record<string, MenuGroupData> = {
  workspace:     { key: 'workspace', label: '工作台', icon: 'AppstoreOutlined', order: 10 },
  review:        { key: 'review', label: '审查中心', icon: 'SafetyCertificateOutlined', order: 20 },
  rules:         { key: 'rules', label: '规则中心', icon: 'SettingOutlined', order: 30 },
  knowledge:     { key: 'knowledge', label: '知识库', icon: 'BookOutlined', order: 40 },
  reports:       { key: 'reports', label: '报告中心', icon: 'FileTextOutlined', order: 50 },
  announcements: { key: 'announcements', label: '警示公告', icon: 'AlertOutlined', order: 60 },
  account:       { key: 'account', label: '用户中心', icon: 'UserOutlined', order: 70 },
  system:        { key: 'system', label: '系统管理', icon: 'ControlOutlined', order: 80 },
  ops:           { key: 'ops', label: '运维中心', icon: 'DashboardOutlined', order: 90 },
};

export const useMenuStore = create<MenuState>((set, get) => ({
  items: [],
  groups: Object.values(MENU_GROUP_MAP),

  setItems: (items: MenuItemData[]) => set({ items }),
  setGroups: (groups: MenuGroupData[]) => set({ groups }),

  getVisibleGroups: (role: UserRole | null) => {
    const { items, groups } = get();
    if (!role) return [];
    // 只显示有至少一个菜单项可见的分组
    const groupsWithItems = new Set(items
      .filter(item => item.visibleTo.includes(role))
      .map(item => item.group));
    return groups.filter(g => groupsWithItems.has(g.key)).sort((a, b) => a.order - b.order);
  },

  getVisibleItems: (groupKey: string, role: UserRole | null) => {
    const { items } = get();
    if (!role) return [];
    return items.filter(item => item.group === groupKey && item.visibleTo.includes(role));
  },
}));
