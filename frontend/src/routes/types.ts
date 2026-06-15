/**
 * 路由类型定义 — 统一路由配置的契约
 */

import type { LazyExoticComponent, ComponentType } from 'react';
import type { UserRole } from '../types';

/** 路由配置项 — 菜单和路由的单一数据源 */
export interface RouteConfig {
  /** URL 路径 (React Router path pattern) */
  path: string;
  /** 页面组件 (支持 lazy import) */
  element: LazyExoticComponent<ComponentType<Record<string, never>>> | ComponentType<Record<string, never>>;
  /** 是否为 index 路由 (对应父路径的默认子路由) */
  index?: boolean;
  /** 页面标题 (用于 PageHeader 和面包屑) */
  title: string;
  /** 副标题 (PageHeader subtitle) */
  subtitle?: string;
  /** 菜单配置 — 不声明则不在菜单中出现 */
  menu?: {
    /** 菜单项唯一 key */
    key: string;
    /** 菜单显示标签 */
    label: string;
    /** 图标名称 (@ant-design/icons 字符串引用) */
    icon: string;
    /** 父分组 key */
    group: string;
    /** 在分组内标记为管理员专有 (adminOnly 高亮) */
    adminOnly?: boolean;
  };
  /** 面包屑项 (不声明则自动从 title 生成) */
  breadcrumb?: { label: string; path?: string }[];
  /** 允许的角色 (基于服务端 role，不是前端推导) */
  requiredRoles?: UserRole[];
  /** 允许的权限 (基于服务端 permissions 数组) */
  requiredPermissions?: string[];
  /** 子路由 */
  children?: RouteConfig[];
}

/** 扁平路径 → RouteConfig 映射，用于权限检查和面包屑生成 */
export type RouteMap = Map<string, RouteConfig>;

/** 菜单构建函数输入 */
export interface MenuBuildInput {
  groups: { key: string; role: string; }[];
  items: { key: string; label: string; path: string; icon: string; group: string; adminOnly?: boolean; visibleTo: UserRole[]; }[];
  role: string;
}
