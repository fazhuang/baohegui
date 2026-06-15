/**
 * 权限服务 — 前端权限判断唯一来源：服务端返回的 permissions 数组
 *
 * 硬规则：
 * 1. 禁止信任 localStorage.role / localStorage.username
 * 2. 禁止从 permissions 数组推导 super_admin
 * 3. isSuperAdmin 必须来自服务端显式字段 (role === 'admin' 且 is_super_admin === true)
 * 4. 后端真实角色模型: admin / user — 前端不凭空声明不存在的角色
 */

import type { PermissionKey, UserRole } from '../types';

// ═══════════════════════════════════════════════════════════════
// 角色显示映射 — 后端 role 字符串 → 前端 UserRole
// ═══════════════════════════════════════════════════════════════

export function mapServerRole(serverRole: string): UserRole {
  if (serverRole === 'admin') return 'admin';
  return 'user';
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
// 角色判断 — 来自真实服务端字段，不做权限集合推导
// ═══════════════════════════════════════════════════════════════

/**
 * 是否为管理员 — 来自服务端 role 字段
 *
 * 注意：后端当前 admin 拥有全部权限，这意味着普通 admin 和超管在前端
 * 无法通过 permissions 数组区分。区分必须依赖服务端额外的 is_super_admin 字段。
 * 在该字段落地之前，前端所有需要区分的入口（/ops, /manage/config 等）
 * 统一对 admin 隐藏。
 */
export function isAdminLike(_permissions: string[], role: UserRole | null): boolean {
  return role === 'admin';
}

/**
 * 是否为超级管理员
 *
 * 当前后端无 super_admin 角色。此函数始终返回 false 直到后端支持。
 * 一旦后端落地 is_super_admin 字段，改为读取该字段。
 *
 * TODO: 后端增加 is_super_admin 字段后，改为:
 *   return role === 'admin' && user.is_super_admin === true
 */
export function isSuperAdminLike(_permissions: string[], _role: UserRole | null): boolean {
  // 后端当前无 super_admin 角色，所有 admin 统一处理。
  // 超管入口暂不暴露，直到后端支持 is_super_admin 字段。
  return false;
}
