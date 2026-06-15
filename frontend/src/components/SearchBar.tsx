/**
 * SearchBar — 搜索输入框 + 高级筛选面板
 *
 * 使用方式:
 *   <SearchBar
 *     value={searchText}
 *     onChange={setSearchText}
 *     onSearch={v => loadData({ search: v })}
 *     placeholder="搜索文件名..."
 *     filters={[
 *       { key: 'risk_level', label: '风险等级', options: [{ value: 'high', label: '高风险' }, ...] },
 *     ]}
 *     filterValues={{ risk_level: 'high' }}
 *     onFilterChange={(key, value) => setFilters(prev => ({ ...prev, [key]: value }))}
 *   />
 */

import React, { useState, useCallback } from 'react';
import {
  Input, Button, Select, Row, Col, theme as antTheme,
} from 'antd';
import {
  SearchOutlined, FilterOutlined, ClearOutlined,
} from '@ant-design/icons';

export interface FilterOption {
  value: string;
  label: string;
}

export interface SearchFilter {
  key: string;
  label: string;
  options: FilterOption[];
}

interface SearchBarProps {
  value?: string;
  onChange?: (value: string) => void;
  onSearch?: (value: string) => void;
  placeholder?: string;
  filters?: SearchFilter[];
  filterValues?: Record<string, string>;
  onFilterChange?: (key: string, value: string) => void;
  onClearAll?: () => void;
  loading?: boolean;
}

const SearchBar: React.FC<SearchBarProps> = ({
  value: controlledValue,
  onChange,
  onSearch,
  placeholder = '搜索...',
  filters,
  filterValues,
  onFilterChange,
  onClearAll,
  loading,
}) => {
  const { token } = antTheme.useToken();
  const [internalValue, setInternalValue] = useState('');
  const [showFilters, setShowFilters] = useState(false);

  const searchValue = controlledValue ?? internalValue;

  const handleSearch = useCallback(
    (val: string) => {
      onSearch?.(val);
    },
    [onSearch],
  );

  const handleChange = useCallback(
    (val: string) => {
      setInternalValue(val);
      onChange?.(val);
    },
    [onChange],
  );

  const hasActiveFilters =
    filterValues && Object.values(filterValues).some(v => v !== undefined && v !== '');

  return (
    <div>
      <Row gutter={[8, 8]} align="middle">
        <Col flex="auto">
          <Input.Search
            prefix={<SearchOutlined style={{ color: token.colorTextQuaternary }} />}
            placeholder={placeholder}
            value={searchValue}
            onChange={e => handleChange(e.target.value)}
            onSearch={handleSearch}
            allowClear
            loading={loading}
            enterButton
          />
        </Col>
        {filters && filters.length > 0 && (
          <Col>
            <Button
              icon={<FilterOutlined />}
              onClick={() => setShowFilters(!showFilters)}
              type={showFilters || hasActiveFilters ? 'primary' : 'default'}
              ghost={!showFilters}
            >
              筛选
              {hasActiveFilters && (
                <span
                  style={{
                    display: 'inline-block',
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: token.colorPrimary,
                    marginLeft: 4,
                  }}
                />
              )}
            </Button>
          </Col>
        )}
        {hasActiveFilters && (
          <Col>
            <Button
              icon={<ClearOutlined />}
              size="small"
              type="text"
              onClick={() => {
                filters?.forEach(f => onFilterChange?.(f.key, ''));
                onClearAll?.();
              }}
            >
              清除筛选
            </Button>
          </Col>
        )}
      </Row>

      {/* 高级筛选面板 */}
      {showFilters && filters && filters.length > 0 && (
        <Row
          gutter={[12, 12]}
          style={{
            marginTop: 12,
            padding: '12px 16px',
            background: token.colorFillAlter,
            borderRadius: 8,
          }}
        >
          {filters.map(f => (
            <Col key={f.key} xs={24} sm={12} md={6}>
              <div style={{ marginBottom: 4, fontSize: 12, color: token.colorTextSecondary }}>
                {f.label}
              </div>
              <Select
                placeholder={`选择${f.label}`}
                value={filterValues?.[f.key] || undefined}
                onChange={v => onFilterChange?.(f.key, v ?? '')}
                allowClear
                style={{ width: '100%' }}
                options={f.options}
              />
            </Col>
          ))}
        </Row>
      )}
    </div>
  );
};

export default SearchBar;
