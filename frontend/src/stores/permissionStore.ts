/**
 * Permission Store — 权限状态 (派生自 authStore)
 *
 * 权限判断只基于服务端返回的 permissions 数组。
 * isSuperAdmin 来自服务端 is_super_admin 字段。
 */

import { create } from 'zustand';

interface PermissionState {
  /** 当前用户 permissions 数组（来自服务端） */
  permissions: string[];
  /** 是否拥有某权限 */
  hasPermission: (perm: string) => boolean;
  /** 是否拥有任一权限 */
  hasAnyPermission: (perms: string[]) => boolean;
  /** 更新权限数组 */
  setPermissions: (perms: string[]) => void;
  /** 重置 */
  reset: () => void;
}

export const usePermissionStore = create<PermissionState>((set, get) => ({
  permissions: [],

  hasPermission: (perm: string) => get().permissions.includes(perm),

  hasAnyPermission: (perms: string[]) => perms.some(p => get().permissions.includes(p)),

  setPermissions: (perms: string[]) => set({ permissions: perms }),

  reset: () => set({ permissions: [] }),
}));
