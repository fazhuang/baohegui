/**
 * DataTable — 统一数据表格组件
 *
 * 封装 Ant Design Table，提供：
 *   - 搜索输入框
 *   - 高级筛选面板
 *   - 批量操作 Toolbar
 *   - 分页
 *   - 行点击回调
 */

import React, { useState, useMemo, useCallback } from 'react';
import {
  Table, Input, Button, Space, Select, Row, Col, Typography, theme as antTheme,
} from 'antd';
import {
  SearchOutlined,
} from '@ant-design/icons';
import type { TablePaginationConfig } from 'antd';
import type { ColumnsType, TableRowSelection } from 'antd/es/table/interface';

const { Text } = Typography;

export interface FilterDef {
  key: string;
  label: string;
  options: { value: string; label: string }[];
  value?: string;
  onChange?: (key: string, value: string) => void;
}

export interface BatchAction<T = Record<string, unknown>> {
  label: string;
  icon?: React.ReactNode;
  onClick: (selectedKeys: React.Key[], selectedRows: T[]) => void;
  danger?: boolean;
}

interface DataTableProps<T extends Record<string, any>> {
  columns: ColumnsType<T>;
  dataSource: T[];
  loading: boolean;
  rowKey: string | ((record: T) => string);
  searchPlaceholder?: string;
  searchValue?: string;
  onSearch?: (value: string) => void;
  filters?: FilterDef[];
  filterValues?: Record<string, string>;
  onFilterChange?: (key: string, value: string) => void;
  batchActions?: BatchAction<T>[];
  pagination?: false | TablePaginationConfig;
  onRowClick?: (record: T) => void;
  scroll?: { x?: number | string; y?: number | string };
  size?: 'small' | 'middle' | 'large';
  showTotal?: boolean;
  emptyText?: string;
}

function DataTable<T extends Record<string, any>>({
  columns,
  dataSource,
  loading,
  rowKey,
  searchPlaceholder = '搜索...',
  searchValue,
  onSearch,
  filters,
  filterValues,
  onFilterChange,
  batchActions,
  pagination,
  onRowClick,
  scroll,
  size = 'middle',
  showTotal = true,
  emptyText = '暂无数据',
}: DataTableProps<T>) {
  const { token } = antTheme.useToken();
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [searchInput, setSearchInput] = useState(searchValue ?? '');

  const handleSearch = useCallback(
    (value: string) => {
      setSearchInput(value);
      onSearch?.(value);
    },
    [onSearch],
  );

  // 行选择配置
  const rowSelection: TableRowSelection<T> | undefined = batchActions
    ? {
        selectedRowKeys,
        onChange: (keys) => {
          setSelectedRowKeys(keys);
        },
      }
    : undefined;

  // 点击行
  const onRow = useMemo(
    () =>
      onRowClick
        ? (record: T) => ({
            onClick: () => onRowClick(record),
            style: { cursor: 'pointer' },
          })
        : undefined,
    [onRowClick],
  );

  return (
    <div>
      {/* 搜索 + 筛选栏 */}
      {(onSearch || (filters && filters.length > 0)) && (
        <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
          {onSearch && (
            <Col xs={24} sm={12} md={8}>
              <Input
                prefix={<SearchOutlined style={{ color: token.colorTextQuaternary }} />}
                placeholder={searchPlaceholder}
                value={searchInput}
                onChange={e => setSearchInput(e.target.value)}
                onPressEnter={() => handleSearch(searchInput)}
                allowClear
                onClear={() => handleSearch('')}
              />
            </Col>
          )}
          {filters?.map(f => (
            <Col key={f.key} xs={12} sm={6} md={4}>
              <Select
                placeholder={f.label}
                value={filterValues?.[f.key] ?? undefined}
                onChange={v => onFilterChange?.(f.key, v)}
                allowClear
                style={{ width: '100%' }}
                options={f.options}
              />
            </Col>
          ))}
        </Row>
      )}

      {/* 批量操作 Toolbar */}
      {batchActions && selectedRowKeys.length > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 16px',
            marginBottom: 12,
            background: token.colorPrimaryBg,
            borderRadius: 8,
            border: `1px solid ${token.colorPrimaryBorder}`,
          }}
        >
          <Text style={{ fontSize: 13 }}>
            已选 <strong>{selectedRowKeys.length}</strong> 项
          </Text>
          <Space>
            {batchActions.map(action => (
              <Button
                key={action.label}
                size="small"
                danger={action.danger}
                icon={action.icon}
                onClick={() => {
                  const selectedRows = dataSource.filter(r => {
                    const key = typeof rowKey === 'function' ? rowKey(r) : r[rowKey];
                    return selectedRowKeys.includes(key);
                  });
                  action.onClick(selectedRowKeys, selectedRows);
                  setSelectedRowKeys([]);
                }}
              >
                {action.label}
              </Button>
            ))}
            <Button size="small" onClick={() => setSelectedRowKeys([])}>
              取消
            </Button>
          </Space>
        </div>
      )}

      {/* 表格 */}
      <Table<T>
        columns={columns}
        dataSource={dataSource}
        loading={loading}
        rowKey={rowKey}
        rowSelection={rowSelection}
        onRow={onRow}
        pagination={
          pagination === false
            ? false
            : {
                defaultPageSize: 20,
                showSizeChanger: true,
                showTotal: showTotal ? (total: number) => `共 ${total} 条` : undefined,
                ...pagination,
              }
        }
        scroll={scroll}
        size={size}
        locale={{ emptyText }}
        style={{ borderRadius: 8 }}
      />
    </div>
  );
}

export default DataTable;
