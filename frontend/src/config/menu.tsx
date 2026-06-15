/**
 * @deprecated 已废弃 — 菜单不再从本文件生成。
 *
 * 真实菜单数据源：routes/routeConfig.tsx (通过 extractMenuItems 派生)。
 * Sidebar 已迁移至 routeConfig 驱动，不再引用本文件。
 *
 * 保留本文件仅供历史参考。请勿新增菜单项到此处。
 */

import type { MenuGroup, MenuItem } from '../types';
import type { UserRole } from '../types';

const A: UserRole[] = ['admin', 'user'];
const ADM: UserRole[] = ['admin'];
const NONE: UserRole[] = [];

/** @deprecated 改用 extractMenuItems(routeConfig) */
export const MENU_GROUPS: MenuGroup[] = [
  { key: 'workspace', label: '工作台', icon: 'AppstoreOutlined', order: 10, visibleTo: A },
  { key: 'review', label: '审查中心', icon: 'SafetyCertificateOutlined', order: 20, visibleTo: A },
  { key: 'rules', label: '规则中心', icon: 'SettingOutlined', order: 30, visibleTo: A },
  { key: 'knowledge', label: '知识库', icon: 'BookOutlined', order: 40, visibleTo: A },
  { key: 'reports', label: '报告中心', icon: 'FileTextOutlined', order: 50, visibleTo: A },
  { key: 'announcements', label: '警示公告', icon: 'AlertOutlined', order: 60, visibleTo: A },
  { key: 'account', label: '用户中心', icon: 'UserOutlined', order: 70, visibleTo: A },
  { key: 'system', label: '系统管理', icon: 'ControlOutlined', order: 80, visibleTo: ADM },
  { key: 'ops', label: '运维中心', icon: 'DashboardOutlined', order: 90, visibleTo: NONE },
];

/** @deprecated 改用 extractMenuItems(routeConfig) */
export const MENU_ITEMS: MenuItem[] = [
  { key: 'dashboard', label: '工作台', path: '/', icon: 'AppstoreOutlined', group: 'workspace', visibleTo: A },
  { key: 'review-new', label: '新建审查', path: '/review', icon: 'UploadOutlined', group: 'review', visibleTo: A },
  { key: 'review-history', label: '审查历史', path: '/review/history', icon: 'HistoryOutlined', group: 'review', visibleTo: A },
  { key: 'rules-overview', label: '规则总览', path: '/rules', icon: 'EyeOutlined', group: 'rules', visibleTo: A },
  { key: 'rules-editor', label: '规则编辑器', path: '/rules/editor', icon: 'EditOutlined', group: 'rules', visibleTo: ADM, adminOnly: true },
  { key: 'rules-versions', label: '规则版本', path: '/rules/versions', icon: 'BranchesOutlined', group: 'rules', visibleTo: ADM, adminOnly: true },
  { key: 'rules-sync', label: '规则同步', path: '/rules/sync', icon: 'SyncOutlined', group: 'rules', visibleTo: ADM, adminOnly: true },
  { key: 'rules-industry', label: '行业配置', path: '/rules/industry', icon: 'ApartmentOutlined', group: 'rules', visibleTo: ADM, adminOnly: true },
  { key: 'kg-graph', label: '知识图谱', path: '/kg', icon: 'NodeIndexOutlined', group: 'knowledge', visibleTo: A },
  { key: 'kg-cases', label: '案例库', path: '/kg/cases', icon: 'FolderOpenOutlined', group: 'knowledge', visibleTo: A },
  { key: 'kg-legal', label: '法规库', path: '/kg/legal', icon: 'ReadOutlined', group: 'knowledge', visibleTo: A },
  { key: 'reports-list', label: '报告列表', path: '/reports', icon: 'UnorderedListOutlined', group: 'reports', visibleTo: A },
  { key: 'reports-feedback', label: '反馈管理', path: '/reports/feedback', icon: 'MessageOutlined', group: 'reports', visibleTo: ADM, adminOnly: true },
  { key: 'ann-list', label: '公告列表', path: '/announcements', icon: 'NotificationOutlined', group: 'announcements', visibleTo: A },
  { key: 'ann-manage', label: '公告管理', path: '/announcements/manage', icon: 'FormOutlined', group: 'announcements', visibleTo: ADM, adminOnly: true },
  { key: 'account-profile', label: '我的账户', path: '/account', icon: 'IdcardOutlined', group: 'account', visibleTo: A },
  { key: 'account-subscription', label: '订阅管理', path: '/account/subscription', icon: 'DollarOutlined', group: 'account', visibleTo: A },
  { key: 'system-users', label: '用户管理', path: '/manage', icon: 'TeamOutlined', group: 'system', visibleTo: ADM },
  { key: 'system-audit', label: '审计日志', path: '/manage/audit', icon: 'AuditOutlined', group: 'system', visibleTo: ADM },
  { key: 'system-quota', label: '配额管理', path: '/manage/quota', icon: 'PieChartOutlined', group: 'system', visibleTo: ADM },
];

function roleMatches(visibleTo: UserRole[], role: string): boolean {
  return visibleTo.includes(role as UserRole);
}

/** @deprecated 改用 extractMenuItems(routeConfig) + useMenuStore.getVisibleGroups() */
export function getVisibleGroups(role: string): MenuGroup[] {
  return MENU_GROUPS
    .filter(g => roleMatches(g.visibleTo, role))
    .sort((a, b) => a.order - b.order);
}

/** @deprecated 改用 extractMenuItems(routeConfig) + useMenuStore.getVisibleItems() */
export function getVisibleItems(groupKey: string, role: string): MenuItem[] {
  return MENU_ITEMS.filter(
    item => item.group === groupKey && roleMatches(item.visibleTo, role),
  );
}

/** @deprecated */
export function getFlatVisibleItems(role: string): MenuItem[] {
  return MENU_ITEMS.filter(item => roleMatches(item.visibleTo, role));
}
