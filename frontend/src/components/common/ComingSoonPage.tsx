/**
 * ComingSoonPage — 统一占位页面
 */

import React from 'react';
import { Result, Button } from 'antd';
import { useNavigate } from 'react-router-dom';
import { ClockCircleOutlined } from '@ant-design/icons';

interface ComingSoonPageProps {
  title?: string;
}

const ComingSoonPage: React.FC<ComingSoonPageProps> = ({ title = '即将上线' }) => {
  const navigate = useNavigate();
  return (
    <Result
      icon={<ClockCircleOutlined />}
      title={title}
      subTitle="该功能正在开发中，敬请期待"
      extra={
        <Button type="primary" onClick={() => navigate('/')}>
          返回工作台
        </Button>
      }
    />
  );
};

export default ComingSoonPage;
