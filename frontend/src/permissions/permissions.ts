/**
 * 权限服务 — 前端权限判断只以服务端返回的 permissions 数组为准
 *
 * 禁止信任 localStorage.role / localStorage.username。
 */

import type { UserRole, PermissionKey } from '../types';

// ═══════════════════════════════════════════════════════════════
// 角色显示映射 — 后端 role → 前端 UserRole
// ═══════════════════════════════════════════════════════════════

const ROLE_DISPLAY_MAP: Record<string, UserRole> = {
  super_admin: 'super_admin',
  admin: 'admin',
  reviewer: 'reviewer',
  agent: 'agent',
  enterprise: 'enterprise',
  // backward compat — 后端暂未迁移的 user → agent
  user: 'agent',
};

export function mapServerRole(serverRole: string): UserRole {
  return ROLE_DISPLAY_MAP[serverRole] ?? 'agent';
}

// ═══════════════════════════════════════════════════════════════
// 权限判断 — 只基于 permissions 数组
// ═══════════════════════════════════════════════════════════════

export function hasPermission(permissions: string[], perm: PermissionKey): boolean {
  return permissions.includes(perm);
}

export function hasAnyPermission(permissions: string[], perms: PermissionKey[]): boolean {
  return perms.some((p) => permissions.includes(p));
}

export function hasAllPermissions(permissions: string[], perms: PermissionKey[]): boolean {
  return perms.every((p) => permissions.includes(p));
}

// ═══════════════════════════════════════════════════════════════
// 高级角色判断 — 基于 permissions 集合推导
// ═══════════════════════════════════════════════════════════════

export function isAdminLike(permissions: string[]): boolean {
  return hasAnyPermission(permissions, ['admin:users', 'rules:write']);
}

export function isSuperAdminLike(permissions: string[]): boolean {
  return hasAnyPermission(permissions, ['kg:seed', 'crawler:trigger']);
}
