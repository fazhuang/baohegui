/**
 * 包合规菜单配置
 *
 * 9 个一级分组，每组包含若干二级菜单项。
 * 每个菜单项声明可见角色列表，由 Sidebar 根据当前用户角色动态渲染。
 *
 * 图标使用 @ant-design/icons 字符串引用，在 Sidebar 中映射为真实组件。
 *
 * 注意: 菜单可见角色必须与后端真实角色 (admin / user) 对齐。
 * 超管入口 (system-config, ops) 当前对所有人隐藏 — 等后端支持 is_super_admin 后启用。
 */

import type { MenuGroup, MenuItem } from '../types';
import type { UserRole } from '../types';

const A: UserRole[] = ['admin', 'user'];   // 全角色可见
const ADM: UserRole[] = ['admin'];           // 仅管理员
const NONE: UserRole[] = [];                  // 暂不开放 (等后端 is_super_admin)

// ═══════════════════════════════════════════════════════════════
// 菜单分组定义
// ═══════════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════════
// 菜单项定义
// ═══════════════════════════════════════════════════════════════

export const MENU_ITEMS: MenuItem[] = [
  // ── 工作台 ──
  { key: 'dashboard', label: '工作台', path: '/', icon: 'AppstoreOutlined', group: 'workspace', visibleTo: A },

  // ── 审查中心 ──
  { key: 'review-new', label: '新建审查', path: '/review', icon: 'UploadOutlined', group: 'review', visibleTo: A },
  { key: 'review-history', label: '审查历史', path: '/review/history', icon: 'HistoryOutlined', group: 'review', visibleTo: A },

  // ── 规则中心 ──
  { key: 'rules-overview', label: '规则总览', path: '/rules', icon: 'EyeOutlined', group: 'rules', visibleTo: A },
  { key: 'rules-editor', label: '规则编辑器', path: '/rules/editor', icon: 'EditOutlined', group: 'rules', visibleTo: ADM, adminOnly: true },
  { key: 'rules-versions', label: '规则版本', path: '/rules/versions', icon: 'BranchesOutlined', group: 'rules', visibleTo: ADM, adminOnly: true },
  { key: 'rules-sync', label: '规则同步', path: '/rules/sync', icon: 'SyncOutlined', group: 'rules', visibleTo: ADM, adminOnly: true },
  { key: 'rules-industry', label: '行业配置', path: '/rules/industry', icon: 'ApartmentOutlined', group: 'rules', visibleTo: ADM, adminOnly: true },

  // ── 知识库 ──
  { key: 'kg-graph', label: '知识图谱', path: '/kg', icon: 'NodeIndexOutlined', group: 'knowledge', visibleTo: A },
  { key: 'kg-cases', label: '案例库', path: '/kg/cases', icon: 'FolderOpenOutlined', group: 'knowledge', visibleTo: A },
  { key: 'kg-legal', label: '法规库', path: '/kg/legal', icon: 'ReadOutlined', group: 'knowledge', visibleTo: A },

  // ── 报告中心 ──
  { key: 'reports-list', label: '报告列表', path: '/reports', icon: 'UnorderedListOutlined', group: 'reports', visibleTo: A },
  { key: 'reports-feedback', label: '反馈管理', path: '/reports/feedback', icon: 'MessageOutlined', group: 'reports', visibleTo: ADM, adminOnly: true },

  // ── 警示公告 ──
  { key: 'ann-list', label: '公告列表', path: '/announcements', icon: 'NotificationOutlined', group: 'announcements', visibleTo: A },
  { key: 'ann-manage', label: '公告管理', path: '/announcements/manage', icon: 'FormOutlined', group: 'announcements', visibleTo: ADM, adminOnly: true },

  // ── 用户中心 ──
  { key: 'account-profile', label: '我的账户', path: '/account', icon: 'IdcardOutlined', group: 'account', visibleTo: A },
  { key: 'account-subscription', label: '订阅管理', path: '/account/subscription', icon: 'DollarOutlined', group: 'account', visibleTo: A },

  // ── 系统管理 ──
  { key: 'system-users', label: '用户管理', path: '/manage', icon: 'TeamOutlined', group: 'system', visibleTo: ADM },
  { key: 'system-audit', label: '审计日志', path: '/manage/audit', icon: 'AuditOutlined', group: 'system', visibleTo: ADM },
  { key: 'system-quota', label: '配额管理', path: '/manage/quota', icon: 'PieChartOutlined', group: 'system', visibleTo: ADM },

  // ── 以下入口暂不开放，等后端支持 is_super_admin 后启用 ──
  // system-roles, system-config, system-model, system-security → NONE
  // ops-* → NONE
];

// ═══════════════════════════════════════════════════════════════
// 工具函数
// ═══════════════════════════════════════════════════════════════

function roleMatches(visibleTo: UserRole[], role: string): boolean {
  return visibleTo.includes(role as UserRole);
}

/** 获取某角色可见的分组列表 */
export function getVisibleGroups(role: string): MenuGroup[] {
  return MENU_GROUPS
    .filter(g => roleMatches(g.visibleTo, role))
    .sort((a, b) => a.order - b.order);
}

/** 获取某分组下某角色可见的菜单项 */
export function getVisibleItems(groupKey: string, role: string): MenuItem[] {
  return MENU_ITEMS.filter(
    item => item.group === groupKey && roleMatches(item.visibleTo, role),
  );
}

/** 获取某角色完整的扁平菜单项列表 */
export function getFlatVisibleItems(role: string): MenuItem[] {
  return MENU_ITEMS.filter(item => roleMatches(item.visibleTo, role));
}
