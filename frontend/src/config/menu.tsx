/**
 * 包合规菜单配置
 *
 * 9 个一级分组，每组包含若干二级菜单项。
 * 每个菜单项声明可见角色列表，由 Sidebar 根据当前用户角色动态渲染。
 *
 * 图标使用 @ant-design/icons 字符串引用，在 Sidebar 中映射为真实组件。
 */

import type { MenuGroup, MenuItem } from '../types';

// ═══════════════════════════════════════════════════════════════
// 菜单分组定义
// ═══════════════════════════════════════════════════════════════

export const MENU_GROUPS: MenuGroup[] = [
  {
    key: 'workspace',
    label: '工作台',
    icon: 'AppstoreOutlined',
    order: 10,
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },
  {
    key: 'review',
    label: '审查中心',
    icon: 'SafetyCertificateOutlined',
    order: 20,
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },
  {
    key: 'rules',
    label: '规则中心',
    icon: 'SettingOutlined',
    order: 30,
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },
  {
    key: 'knowledge',
    label: '知识库',
    icon: 'BookOutlined',
    order: 40,
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },
  {
    key: 'reports',
    label: '报告中心',
    icon: 'FileTextOutlined',
    order: 50,
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },
  {
    key: 'announcements',
    label: '警示公告',
    icon: 'AlertOutlined',
    order: 60,
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },
  {
    key: 'account',
    label: '用户中心',
    icon: 'UserOutlined',
    order: 70,
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },
  {
    key: 'system',
    label: '系统管理',
    icon: 'ControlOutlined',
    order: 80,
    visibleTo: ['super_admin', 'admin'],
  },
  {
    key: 'ops',
    label: '运维中心',
    icon: 'DashboardOutlined',
    order: 90,
    visibleTo: ['super_admin'],
  },
];

// ═══════════════════════════════════════════════════════════════
// 菜单项定义
// ═══════════════════════════════════════════════════════════════

export const MENU_ITEMS: MenuItem[] = [
  // ── 工作台 ──
  {
    key: 'dashboard',
    label: '工作台',
    path: '/',
    icon: 'AppstoreOutlined',
    group: 'workspace',
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },

  // ── 审查中心 ──
  {
    key: 'review-new',
    label: '新建审查',
    path: '/review',
    icon: 'UploadOutlined',
    group: 'review',
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },
  {
    key: 'review-history',
    label: '审查历史',
    path: '/review/history',
    icon: 'HistoryOutlined',
    group: 'review',
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },

  // ── 规则中心 (查看) — 所有人可见 ──
  {
    key: 'rules-overview',
    label: '规则总览',
    path: '/rules',
    icon: 'EyeOutlined',
    group: 'rules',
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },
  // ── 规则中心 (管理) — 仅管理员可见 ──
  {
    key: 'rules-editor',
    label: '规则编辑器',
    path: '/rules/editor',
    icon: 'EditOutlined',
    group: 'rules',
    visibleTo: ['super_admin', 'admin'],
    adminOnly: true,
  },
  {
    key: 'rules-versions',
    label: '规则版本',
    path: '/rules/versions',
    icon: 'BranchesOutlined',
    group: 'rules',
    visibleTo: ['super_admin', 'admin'],
    adminOnly: true,
  },
  {
    key: 'rules-sync',
    label: '规则同步',
    path: '/rules/sync',
    icon: 'SyncOutlined',
    group: 'rules',
    visibleTo: ['super_admin', 'admin'],
    adminOnly: true,
  },
  {
    key: 'rules-industry',
    label: '行业规则配置',
    path: '/rules/industry',
    icon: 'ApartmentOutlined',
    group: 'rules',
    visibleTo: ['super_admin', 'admin'],
    adminOnly: true,
  },

  // ── 知识库 ──
  {
    key: 'kg-graph',
    label: '知识图谱',
    path: '/kg',
    icon: 'NodeIndexOutlined',
    group: 'knowledge',
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },
  {
    key: 'kg-cases',
    label: '案例库',
    path: '/kg/cases',
    icon: 'FolderOpenOutlined',
    group: 'knowledge',
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },
  {
    key: 'kg-legal',
    label: '法规库',
    path: '/kg/legal',
    icon: 'ReadOutlined',
    group: 'knowledge',
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },

  // ── 报告中心 ──
  {
    key: 'reports-list',
    label: '报告列表',
    path: '/reports',
    icon: 'UnorderedListOutlined',
    group: 'reports',
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },
  {
    key: 'reports-feedback',
    label: '反馈管理',
    path: '/reports/feedback',
    icon: 'MessageOutlined',
    group: 'reports',
    visibleTo: ['super_admin', 'admin', 'reviewer'],
    adminOnly: true,
  },

  // ── 警示公告 ──
  {
    key: 'ann-list',
    label: '公告列表',
    path: '/announcements',
    icon: 'NotificationOutlined',
    group: 'announcements',
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },
  {
    key: 'ann-manage',
    label: '公告管理',
    path: '/announcements/manage',
    icon: 'FormOutlined',
    group: 'announcements',
    visibleTo: ['super_admin', 'admin'],
    adminOnly: true,
  },

  // ── 用户中心 ──
  {
    key: 'account-profile',
    label: '我的账户',
    path: '/account',
    icon: 'IdcardOutlined',
    group: 'account',
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },
  {
    key: 'account-subscription',
    label: '订阅管理',
    path: '/account/subscription',
    icon: 'DollarOutlined',
    group: 'account',
    visibleTo: ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  },

  // ── 系统管理 ──
  {
    key: 'system-users',
    label: '用户管理',
    path: '/manage/users',
    icon: 'TeamOutlined',
    group: 'system',
    visibleTo: ['super_admin', 'admin'],
  },
  {
    key: 'system-roles',
    label: '角色管理',
    path: '/manage/roles',
    icon: 'SafetyOutlined',
    group: 'system',
    visibleTo: ['super_admin'],
    adminOnly: true,
  },
  {
    key: 'system-audit',
    label: '审计日志',
    path: '/manage/audit',
    icon: 'AuditOutlined',
    group: 'system',
    visibleTo: ['super_admin', 'admin'],
  },
  {
    key: 'system-quota',
    label: '配额管理',
    path: '/manage/quota',
    icon: 'PieChartOutlined',
    group: 'system',
    visibleTo: ['super_admin', 'admin'],
  },
  {
    key: 'system-config',
    label: '系统配置',
    path: '/manage/config',
    icon: 'ToolOutlined',
    group: 'system',
    visibleTo: ['super_admin'],
    adminOnly: true,
  },
  {
    key: 'system-model',
    label: '模型配置',
    path: '/manage/model',
    icon: 'RobotOutlined',
    group: 'system',
    visibleTo: ['super_admin'],
    adminOnly: true,
  },
  {
    key: 'system-security',
    label: '安全中心',
    path: '/manage/security',
    icon: 'LockOutlined',
    group: 'system',
    visibleTo: ['super_admin'],
    adminOnly: true,
  },

  // ── 运维中心 ──
  {
    key: 'ops-scheduler',
    label: '规则同步调度',
    path: '/ops/scheduler',
    icon: 'ClockCircleOutlined',
    group: 'ops',
    visibleTo: ['super_admin'],
  },
  {
    key: 'ops-crawler',
    label: '案例采集引擎',
    path: '/ops/crawler',
    icon: 'GlobalOutlined',
    group: 'ops',
    visibleTo: ['super_admin'],
  },
  {
    key: 'ops-kg-seed',
    label: '知识图谱播种',
    path: '/ops/kg-seed',
    icon: 'ThunderboltOutlined',
    group: 'ops',
    visibleTo: ['super_admin'],
  },
  {
    key: 'ops-health',
    label: '系统健康',
    path: '/ops/health',
    icon: 'HeartOutlined',
    group: 'ops',
    visibleTo: ['super_admin'],
  },
];

// ═══════════════════════════════════════════════════════════════
// 工具函数
// ═══════════════════════════════════════════════════════════════

/** 获取某角色可见的分组列表 */
export function getVisibleGroups(role: string): MenuGroup[] {
  return MENU_GROUPS
    .filter(g => g.visibleTo.includes(role as any))
    .sort((a, b) => a.order - b.order);
}

/** 获取某分组下某角色可见的菜单项 */
export function getVisibleItems(groupKey: string, role: string): MenuItem[] {
  return MENU_ITEMS.filter(
    item => item.group === groupKey && item.visibleTo.includes(role as any),
  );
}

/** 获取某角色完整的扁平菜单项列表 */
export function getFlatVisibleItems(role: string): MenuItem[] {
  return MENU_ITEMS.filter(item => item.visibleTo.includes(role as any));
}
