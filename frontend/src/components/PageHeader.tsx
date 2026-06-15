/**
 * PageHeader — 统一页面标题组件
 *
 * 提供页面标题 + 面包屑导航 + 右侧操作区域。
 *
 * 使用方式:
 *   <PageHeader
 *     title="审查中心"
 *     breadcrumb={[{ label: '审查中心' }, { label: '新建审查' }]}
 *     extra={<Button>导出</Button>}
 *   />
 */

import React from 'react';
import { Breadcrumb, Typography, Space } from 'antd';
import { useNavigate } from 'react-router-dom';

const { Title } = Typography;

export interface BreadcrumbItem {
  label: string;
  path?: string;
}

interface PageHeaderProps {
  title: string;
  breadcrumb?: BreadcrumbItem[];
  extra?: React.ReactNode;
  subtitle?: string;
}

const PageHeader: React.FC<PageHeaderProps> = ({ title, breadcrumb, extra, subtitle }) => {
  const navigate = useNavigate();

  return (
    <div style={{ marginBottom: 24 }}>
      {/* 面包屑 */}
      {breadcrumb && breadcrumb.length > 0 && (
        <Breadcrumb
          items={breadcrumb.map((item, idx) => ({
            title:
              item.path && idx < breadcrumb.length - 1 ? (
                <a onClick={() => navigate(item.path!)}>{item.label}</a>
              ) : (
                item.label
              ),
          }))}
          style={{ marginBottom: 8 }}
        />
      )}

      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <Title level={3} style={{ margin: 0, fontSize: 20 }}>
            {title}
          </Title>
          {subtitle && (
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              {subtitle}
            </Typography.Text>
          )}
        </div>
        {extra && <Space>{extra}</Space>}
      </div>
    </div>
  );
};

export default PageHeader;
