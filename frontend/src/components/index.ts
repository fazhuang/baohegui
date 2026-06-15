/**
 * 共享组件统一导出 (Barrel)
 *
 * 所有通用组件统一从本文件导入：
 *   import { PageHeader, DataTable, StatusTag } from '../components';
 */

export { default as PageHeader } from './PageHeader';
export type { BreadcrumbItem } from './PageHeader';

export { default as DataTable } from './DataTable';
export type { FilterDef, BatchAction } from './DataTable';

export { default as SearchBar } from './SearchBar';
export type { SearchFilter, FilterOption } from './SearchBar';

export { default as DetailDrawer } from './DetailDrawer';

export { default as StatusTag } from './StatusTag';

export { default as EmptyState } from './EmptyState';

export { default as ErrorBoundary } from './ErrorBoundary';

export { default as ComingSoonPage } from './common/ComingSoonPage';
