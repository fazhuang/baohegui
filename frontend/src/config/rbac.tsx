/**
 * @deprecated 已废弃 — RBAC 配置不再从本文件读取。
 *
 * 权限判断统一走 zustand stores:
 *   - useAuthStore.hasPerm / isAdmin / isSuperAdmin
 *   - usePermissionStore.hasPermission / hasAnyPermission
 *
 * 路由权限统一在 routeConfig.tsx 中声明 requiredRoles / requiredPermissions，
 * 由 renderRoutes.tsx 统一套用 RouteGuard。
 *
 * 保留本文件仅供历史参考。请勿新增角色或权限到此文件。
 */

import type { UserRole, PermissionKey } from '../types';

/** @deprecated 改用 useAuthStore.isAdmin() */
export interface RoleDef {
  key: UserRole;
  label: string;
  description: string;
}

/** @deprecated */
export const ALL_ROLES: RoleDef[] = [
  { key: 'admin', label: '管理员', description: '用户管理、规则管理、系统配置' },
  { key: 'user', label: '普通用户', description: '上传文件、发起审查、查看报告' },
];

/** @deprecated 改用 useAuthStore.hasPerm() */
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

/** @deprecated */
export function hasRolePermission(role: UserRole, permission: PermissionKey): boolean {
  return ROLE_PERMISSIONS[role]?.has(permission) ?? false;
}

/** @deprecated */
export function isAdminRole(role: UserRole): boolean {
  return role === 'admin';
}

/** @deprecated */
export function roleLabel(role: UserRole): string {
  const found = ALL_ROLES.find(r => r.key === role);
  return found?.label ?? role;
}

/** @deprecated 改用 extractMenuItems(routeConfig) */
export const GROUP_VISIBILITY: Record<string, UserRole[]> = {
  workspace:    ['admin', 'user'],
  review:       ['admin', 'user'],
  rules:        ['admin', 'user'],
  'rules-manage': ['admin'],
  knowledge:    ['admin', 'user'],
  reports:      ['admin', 'user'],
  'reports-manage': ['admin'],
  announcements: ['admin', 'user'],
  'announce-manage': ['admin'],
  account:      ['admin', 'user'],
  system:       ['admin'],
  'system-config': [],
  ops:          [],
};
