/**
 * 包合规 RBAC 配置
 *
 * 当前后端真实角色模型: admin / user。
 * 本文件为前端配置中心，角色能力从权限集合派生。
 *
 * 警告：不得凭空声明后端不存在的角色。
 * 如需扩展 5 角色体系，必须后端同步支持。
 */

import type { UserRole, PermissionKey } from '../types';

// ═══════════════════════════════════════════════════════════════
// 角色定义 — 与后端 models/user.py role 字段对齐
// ═══════════════════════════════════════════════════════════════

export interface RoleDef {
  key: UserRole;
  label: string;
  description: string;
}

export const ALL_ROLES: RoleDef[] = [
  { key: 'admin', label: '管理员', description: '用户管理、规则管理、系统配置' },
  { key: 'user', label: '普通用户', description: '上传文件、发起审查、查看报告' },
];

// ═══════════════════════════════════════════════════════════════
// 权限矩阵 — 与后端 ROLE_PERMISSIONS 对齐
// ═══════════════════════════════════════════════════════════════

export const ROLE_PERMISSIONS: Record<UserRole, Set<PermissionKey>> = {
  admin: new Set<PermissionKey>([
    'file:upload', 'file:check',
    'report:view', 'report:download', 'report:list_all',
    'rules:read', 'rules:write', 'rules:sync',
    'admin:users', 'admin:audit', 'admin:billing',
    'stats:dashboard',
    'kg:read', 'kg:seed',
    'crawler:read', 'crawler:trigger',
  ]),

  user: new Set<PermissionKey>([
    'file:upload', 'file:check',
    'report:view', 'report:download',
    'rules:read',
    'kg:read',
  ]),
};

// ═══════════════════════════════════════════════════════════════
// 权限工具函数
// ═══════════════════════════════════════════════════════════════

export function hasRolePermission(role: UserRole, permission: PermissionKey): boolean {
  return ROLE_PERMISSIONS[role]?.has(permission) ?? false;
}

export function isAdminRole(role: UserRole): boolean {
  return role === 'admin';
}

export function roleLabel(role: UserRole): string {
  const found = ALL_ROLES.find(r => r.key === role);
  return found?.label ?? role;
}

// ═══════════════════════════════════════════════════════════════
// 菜单可见性 — 菜单分组可见角色
// ═══════════════════════════════════════════════════════════════

export const GROUP_VISIBILITY: Record<string, UserRole[]> = {
  'workspace':    ['admin', 'user'],
  'review':       ['admin', 'user'],
  'rules':        ['admin', 'user'],
  'rules-manage': ['admin'],
  'knowledge':    ['admin', 'user'],
  'reports':      ['admin', 'user'],
  'reports-manage': ['admin'],
  'announcements': ['admin', 'user'],
  'announce-manage': ['admin'],
  'account':      ['admin', 'user'],
  'system':       ['admin'],
  'system-config': [],
  'ops':          [],
};
