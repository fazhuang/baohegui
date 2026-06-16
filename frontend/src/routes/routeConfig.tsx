/**
 * 统一路由配置 — 菜单/路由/权限/面包屑的单一数据源
 *
 * 设计原则:
 * 1. 菜单从 routeConfig 自动生成 — 不允许单独维护菜单列表
 * 2. 权限在路由层声明 (requiredRoles / requiredPermissions)
 * 3. 面包屑从 title 和层级自动生成
 * 4. 新增页面只需在此文件加一条
 * 5. App.tsx 的路由树由 renderRoutes() 从此文件自动生成
 *
 * requiredRoles 语义:
 *   undefined  = 公开路由 (无需登录)
 *   []         = 需要登录但禁止访问 (403)
 *   ['admin']  = 仅管理员
 *   ['admin','user'] = 所有已登录用户
 */

import { lazy } from 'react';
import type { RouteConfig } from './types';

// ── 懒加载页面 ──────────────────────────────────────────────────
const LoginPage = lazy(() => import('../pages/Login'));
const ForgotPassword = lazy(() => import('../pages/ForgotPassword'));
const ResetPassword = lazy(() => import('../pages/ResetPassword'));
const DashboardPage = lazy(() => import('../pages/Dashboard'));
const UploadPage = lazy(() => import('../pages/Upload'));
const ReportPage = lazy(() => import('../pages/Report'));
const HistoryPage = lazy(() => import('../pages/History'));
const AdminRulesPage = lazy(() => import('../pages/AdminRules'));
const AdminPanel = lazy(() => import('../pages/AdminPanel'));
const ReviewCenter = lazy(() => import('../pages/ReviewCenter'));
const RulesCenter = lazy(() => import('../pages/RulesCenter'));
const KnowledgeBase = lazy(() => import('../pages/KnowledgeBase'));
const ReportCenter = lazy(() => import('../pages/ReportCenter'));
const Announcements = lazy(() => import('../pages/Announcements'));
const UserCenter = lazy(() => import('../pages/UserCenter'));
const SystemManage = lazy(() => import('../pages/SystemManage'));
const ComingSoonPage = lazy(() => import('../components/common/ComingSoonPage'));

/** 全局 404 页面引用保留在 renderRoutes.tsx / AppRoutes.tsx */

// ═══════════════════════════════════════════════════════════════
// 路由树 — 真实应用路由的单一数据源
// ═══════════════════════════════════════════════════════════════

export const routeConfig: RouteConfig[] = [
  // ── 公开路由 ──────────────────────────────────────────────────
  {
    path: '/login',
    element: LoginPage,
    title: '登录',
  },
  {
    path: '/forgot-password',
    element: ForgotPassword,
    title: '忘记密码',
  },
  {
    path: '/reset-password',
    element: ResetPassword,
    title: '重置密码',
  },

  // ── 受保护路由 (父级: ProtectedShell) ──────────────────────────
  {
    path: '/',
    element: DashboardPage,
    index: true,
    title: '工作台',
    menu: { key: 'dashboard', label: '工作台', icon: 'AppstoreOutlined', group: 'workspace' },
    requiredRoles: ['admin', 'user'],
  },
  {
    path: '/report/:id',
    element: ReportPage,
    title: '审查报告',
    requiredRoles: ['admin', 'user'],
  },

  // ── 审查中心 ──────────────────────────────────────────────────
  {
    path: '/review',
    element: ReviewCenter,
    title: '审查中心',
    subtitle: '上传招标文件并进行合规审查',
    menu: { key: 'review', label: '审查中心', icon: 'UploadOutlined', group: 'review' },
    requiredRoles: ['admin', 'user'],
    children: [
      {
        path: '/review',
        element: UploadPage,
        index: true,
        title: '新建审查',
        menu: { key: 'review-new', label: '新建审查', icon: 'UploadOutlined', group: 'review' },
        requiredRoles: ['admin', 'user'],
      },
      {
        path: '/review/history',
        element: HistoryPage,
        title: '审查历史',
        menu: { key: 'review-history', label: '审查历史', icon: 'HistoryOutlined', group: 'review' },
        requiredRoles: ['admin', 'user'],
      },
    ],
  },

  // ── 报告中心 ──────────────────────────────────────────────────
  {
    path: '/reports',
    element: ReportCenter,
    title: '报告中心',
    subtitle: '查看、下载和反馈合规审查报告',
    menu: { key: 'reports', label: '报告中心', icon: 'FileTextOutlined', group: 'reports' },
    requiredRoles: ['admin', 'user'],
    children: [
      {
        path: '/reports',
        element: HistoryPage,
        index: true,
        title: '报告列表',
        menu: { key: 'reports-list', label: '报告列表', icon: 'UnorderedListOutlined', group: 'reports' },
        requiredRoles: ['admin', 'user'],
      },
      {
        path: '/reports/feedback',
        element: ComingSoonPage,
        title: '反馈管理',
        menu: { key: 'reports-feedback', label: '反馈管理', icon: 'MessageOutlined', group: 'reports', adminOnly: true },
        requiredRoles: ['admin'],
      },
    ],
  },

  // ── 知识库 ────────────────────────────────────────────────────
  {
    path: '/kg',
    element: KnowledgeBase,
    title: '知识库',
    subtitle: '招标投标知识图谱、投诉案例与法规依据',
    menu: { key: 'kg', label: '知识库', icon: 'BookOutlined', group: 'knowledge' },
    requiredRoles: ['admin', 'user'],
    children: [
      {
        path: '/kg',
        element: ComingSoonPage,
        index: true,
        title: '知识图谱',
        menu: { key: 'kg-graph', label: '知识图谱', icon: 'NodeIndexOutlined', group: 'knowledge' },
        requiredRoles: ['admin', 'user'],
      },
      {
        path: '/kg/cases',
        element: ComingSoonPage,
        title: '案例库',
        menu: { key: 'kg-cases', label: '案例库', icon: 'FolderOpenOutlined', group: 'knowledge' },
        requiredRoles: ['admin', 'user'],
      },
      {
        path: '/kg/legal',
        element: ComingSoonPage,
        title: '法规库',
        menu: { key: 'kg-legal', label: '法规库', icon: 'ReadOutlined', group: 'knowledge' },
        requiredRoles: ['admin', 'user'],
      },
    ],
  },

  // ── 警示公告 ──────────────────────────────────────────────────
  {
    path: '/announcements',
    element: Announcements,
    title: '警示公告',
    menu: { key: 'announcements', label: '警示公告', icon: 'AlertOutlined', group: 'announcements' },
    requiredRoles: ['admin', 'user'],
    children: [
      {
        path: '/announcements',
        element: ComingSoonPage,
        index: true,
        title: '公告列表',
        menu: { key: 'ann-list', label: '公告列表', icon: 'NotificationOutlined', group: 'announcements' },
        requiredRoles: ['admin', 'user'],
      },
      {
        path: '/announcements/manage',
        element: ComingSoonPage,
        title: '公告管理',
        menu: { key: 'ann-manage', label: '公告管理', icon: 'FormOutlined', group: 'announcements', adminOnly: true },
        requiredRoles: ['admin'],
      },
    ],
  },

  // ── 用户中心 ──────────────────────────────────────────────────
  {
    path: '/account',
    element: UserCenter,
    title: '用户中心',
    menu: { key: 'account', label: '用户中心', icon: 'UserOutlined', group: 'account' },
    requiredRoles: ['admin', 'user'],
    children: [
      {
        path: '/account',
        element: ComingSoonPage,
        index: true,
        title: '我的账户',
        menu: { key: 'account-profile', label: '我的账户', icon: 'IdcardOutlined', group: 'account' },
        requiredRoles: ['admin', 'user'],
      },
      {
        path: '/account/subscription',
        element: ComingSoonPage,
        title: '订阅管理',
        menu: { key: 'account-subscription', label: '订阅管理', icon: 'DollarOutlined', group: 'account' },
        requiredRoles: ['admin', 'user'],
      },
    ],
  },

  // ── 规则中心 (admin only) ─────────────────────────────────────
  {
    path: '/rules',
    element: RulesCenter,
    title: '规则中心',
    subtitle: '管理合规审查规则、同步平台规则',
    menu: { key: 'rules', label: '规则中心', icon: 'SettingOutlined', group: 'rules' },
    requiredRoles: ['admin'],
    children: [
      {
        path: '/rules',
        element: AdminRulesPage,
        index: true,
        title: '规则总览',
        menu: { key: 'rules-overview', label: '规则总览', icon: 'EyeOutlined', group: 'rules' },
        requiredRoles: ['admin'],
      },
      {
        path: '/rules/editor',
        element: AdminRulesPage,
        title: '规则编辑器',
        menu: { key: 'rules-editor', label: '规则编辑器', icon: 'EditOutlined', group: 'rules', adminOnly: true },
        requiredRoles: ['admin'],
      },
      {
        path: '/rules/versions',
        element: AdminRulesPage,
        title: '规则版本',
        menu: { key: 'rules-versions', label: '规则版本', icon: 'BranchesOutlined', group: 'rules', adminOnly: true },
        requiredRoles: ['admin'],
      },
      {
        path: '/rules/sync',
        element: AdminRulesPage,
        title: '规则同步',
        menu: { key: 'rules-sync', label: '规则同步', icon: 'SyncOutlined', group: 'rules', adminOnly: true },
        requiredRoles: ['admin'],
      },
      {
        path: '/rules/industry',
        element: ComingSoonPage,
        title: '行业配置',
        menu: { key: 'rules-industry', label: '行业配置', icon: 'ApartmentOutlined', group: 'rules', adminOnly: true },
        requiredRoles: ['admin'],
      },
    ],
  },

  // ── 系统管理 (admin only) ─────────────────────────────────────
  {
    path: '/manage',
    element: SystemManage,
    title: '系统管理',
    subtitle: '用户、审计、配额与系统配置',
    menu: { key: 'system', label: '系统管理', icon: 'ControlOutlined', group: 'system' },
    requiredRoles: ['admin'],
    children: [
      {
        path: '/manage',
        element: AdminPanel,
        index: true,
        title: '用户管理',
        menu: { key: 'system-users', label: '用户管理', icon: 'TeamOutlined', group: 'system' },
        requiredRoles: ['admin'],
      },
      {
        path: '/manage/audit',
        element: AdminPanel,
        title: '审计日志',
        menu: { key: 'system-audit', label: '审计日志', icon: 'AuditOutlined', group: 'system' },
        requiredRoles: ['admin'],
      },
      {
        path: '/manage/quota',
        element: AdminPanel,
        title: '配额管理',
        menu: { key: 'system-quota', label: '配额管理', icon: 'PieChartOutlined', group: 'system' },
        requiredRoles: ['admin'],
      },
    ],
  },

  // ── 向后兼容重定向 ────────────────────────────────────────────
  {
    path: '/upload',
    redirect: '/review',
    title: '重定向',
  },
  {
    path: '/history',
    redirect: '/review/history',
    title: '重定向',
  },
  {
    path: '/admin/rules',
    redirect: '/rules',
    title: '重定向',
  },
  {
    path: '/admin/panel',
    redirect: '/manage',
    title: '重定向',
  },
];

// ═══════════════════════════════════════════════════════════════
// 工具函数
// ═══════════════════════════════════════════════════════════════

/** 扁平化路由列表 (用于匹配和权限检查) */
export function flattenRoutes(configs: RouteConfig[]): RouteConfig[] {
  const result: RouteConfig[] = [];
  for (const c of configs) {
    result.push(c);
    if (c.children) {
      result.push(...flattenRoutes(c.children));
    }
  }
  return result;
}

/** 从 routeConfig 提取菜单项 */
export interface ExtractedMenuItem {
  key: string;
  label: string;
  path: string;
  icon: string;
  group: string;
  adminOnly?: boolean;
  requiredRoles: string[];
}

export function extractMenuItems(configs: RouteConfig[]): ExtractedMenuItem[] {
  const items: ExtractedMenuItem[] = [];
  const seen = new Set<string>();

  for (const c of flattenRoutes(configs)) {
    if (!c.menu) continue;
    if (seen.has(c.menu.key)) continue;
    seen.add(c.menu.key);
    items.push({
      key: c.menu.key,
      label: c.menu.label,
      path: c.path,
      icon: c.menu.icon,
      group: c.menu.group,
      adminOnly: c.menu.adminOnly,
      requiredRoles: c.requiredRoles ?? [],
    });
  }
  return items;
}
