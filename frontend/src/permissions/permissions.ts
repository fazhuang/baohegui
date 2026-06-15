/**
 * 权限服务 — 前端权限判断唯一来源：服务端返回的 permissions 数组
 *
 * 硬规则：
 * 1. 禁止信任 localStorage.role / localStorage.username
 * 2. 禁止从 permissions 数组推导管理员身份
 * 3. 超管判定来自服务端显式字段 is_super_admin (后端暂未落地，前端统一返回 false)
 * 4. 后端真实角色模型: admin / user — 前端不凭空声明不存在的角色
 *
 * 注意：is_super_admin 仅为从后端传递的数据字段，不作为前端独立的角色枚举值。
 * 前端角色枚举只有 'admin' 和 'user'。
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
// 角色判断 — 来自真实服务端字段
// ═══════════════════════════════════════════════════════════════

/** 是否为管理员 — 基于服务端 role 字段 */
export function isAdminLike(_permissions: string[], role: UserRole | null): boolean {
  return role === 'admin';
}

/**
 * 是否为超级管理员
 *
 * 依赖服务端 is_super_admin 字段。后端尚未落地该字段，当前始终返回 false。
 * 相关入口（/ops 等）统一隐藏，直到后端支持。
 */
export function isSuperAdminLike(_permissions: string[], _role: UserRole | null): boolean {
  return false;
}
