/**
 * 包合规 RBAC 配置
 *
 * 5 角色体系：super_admin / admin / reviewer / agent / enterprise
 * 权限矩阵覆盖 12 个权限域 × 5 个角色
 *
 * 使用方式:
 *   import { ROLE_PERMISSIONS, hasPermission, MENU_VISIBILITY } from '@/config/rbac';
 */

import type { UserRole, PermissionKey } from '../types';

// ═══════════════════════════════════════════════════════════════
// 角色定义
// ═══════════════════════════════════════════════════════════════

export interface RoleDef {
  key: UserRole;
  label: string;
  description: string;
}

export const ALL_ROLES: RoleDef[] = [
  { key: 'super_admin', label: '超级管理员', description: '系统最高权限，可管理所有配置和安全中心' },
  { key: 'admin', label: '普通管理员', description: '日常运营管理，用户管理、规则管理、报告查看' },
  { key: 'reviewer', label: '审查员', description: '执行审查、复核报告、提交反馈、查询法规' },
  { key: 'agent', label: '招标代理机构', description: '上传文件、发起审查、查看报告、下载导出' },
  { key: 'enterprise', label: '企业用户', description: '上传自检、查看自己的报告、下载导出' },
];

// ═══════════════════════════════════════════════════════════════
// 权限矩阵 — 12 权限域 × 5 角色
// ═══════════════════════════════════════════════════════════════

export const ROLE_PERMISSIONS: Record<UserRole, Set<PermissionKey>> = {
  super_admin: new Set<PermissionKey>([
    'file:upload', 'file:check',
    'report:view', 'report:download', 'report:list_all',
    'rules:read', 'rules:write', 'rules:sync',
    'admin:users', 'admin:audit', 'admin:billing',
    'stats:dashboard',
    'kg:read', 'kg:seed',
    'crawler:read', 'crawler:trigger',
  ]),

  admin: new Set<PermissionKey>([
    'file:upload', 'file:check',
    'report:view', 'report:download', 'report:list_all',
    'rules:read', 'rules:write', 'rules:sync',
    'admin:users', 'admin:audit', 'admin:billing',
    'stats:dashboard',
    'kg:read',
    'crawler:read',
  ]),

  reviewer: new Set<PermissionKey>([
    'file:upload', 'file:check',
    'report:view', 'report:download', 'report:list_all',
    'rules:read',
    'kg:read',
    'crawler:read',
  ]),

  agent: new Set<PermissionKey>([
    'file:upload', 'file:check',
    'report:view', 'report:download',
    'rules:read',
    'kg:read',
    'crawler:read',
  ]),

  enterprise: new Set<PermissionKey>([
    'file:upload', 'file:check',
    'report:view', 'report:download',
    'rules:read',
  ]),
};

// ═══════════════════════════════════════════════════════════════
// 权限工具函数
// ═══════════════════════════════════════════════════════════════

/** 检查角色是否拥有某权限 */
export function hasPermission(role: UserRole | string, permission: PermissionKey): boolean {
  const r = role as UserRole;
  return ROLE_PERMISSIONS[r]?.has(permission) ?? false;
}

/** 检查当前用户是否拥有任一角色的功能（用于 UI 条件渲染） */
export function isAdminRole(role: UserRole | string): boolean {
  return role === 'super_admin' || role === 'admin';
}

export function isSuperAdmin(role: UserRole | string): boolean {
  return role === 'super_admin';
}

export function canManageUsers(role: UserRole | string): boolean {
  return isAdminRole(role);
}

export function canManageRules(role: UserRole | string): boolean {
  return isAdminRole(role);
}

export function canAccessOpsCenter(role: UserRole | string): boolean {
  return role === 'super_admin';
}

/** 将角色映射为显示名称 */
export function roleLabel(role: UserRole | string): string {
  const found = ALL_ROLES.find(r => r.key === role);
  return found?.label ?? role;
}

// ═══════════════════════════════════════════════════════════════
// 菜单可见性 — 一级分组 → 可见角色
// ═══════════════════════════════════════════════════════════════

/** 一级菜单分组的可见角色映射 */
export const GROUP_VISIBILITY: Record<string, UserRole[]> = {
  'workspace':       ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  'review':          ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  'rules':           ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  'rules-manage':    ['super_admin', 'admin'],
  'knowledge':       ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  'knowledge-manage':['super_admin'],
  'reports':         ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  'reports-manage':  ['super_admin', 'admin', 'reviewer'],
  'announcements':   ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  'announce-manage': ['super_admin', 'admin'],
  'account':         ['super_admin', 'admin', 'reviewer', 'agent', 'enterprise'],
  'system':          ['super_admin', 'admin'],
  'system-config':   ['super_admin'],
  'ops':             ['super_admin'],
};
