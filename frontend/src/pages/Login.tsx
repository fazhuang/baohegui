/**
 * LoginPage — 登录/注册页面
 *
 * 编排层：全部业务逻辑在此，无额外拆分。
 * localStorage 操作通过 useRememberMe hook 封装。
 */

import React, { useState, useEffect } from 'react';
import { Card, Form, Input, Button, Typography, message, Alert, Spin, Tabs, Checkbox } from 'antd';
import { UserOutlined, LockOutlined, ReloadOutlined, TeamOutlined, MailOutlined, ProfileOutlined } from '@ant-design/icons';
import { useAuthStore } from '../stores/authStore';
import { registerUser } from '../services/api';
import { getErrorMessage } from '../utils/error';
import { useNavigate } from 'react-router-dom';
import { useRememberMe } from '../features/login/hooks/useRememberMe';

interface LoginProps { onLogin?: () => void; }

const LoginPage: React.FC<LoginProps> = (props) => {
  const [loading, setLoading] = useState(false);
  const [regLoading, setRegLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [serverDown, setServerDown] = useState(false);
  const [tab, setTab] = useState('login');
  const [rememberMe, setRememberMe] = useState(() => localStorage.getItem('remember_me') === 'true');
  const navigate = useNavigate();
  const authLogin = useAuthStore(s => s.login);
  const remember = useRememberMe();

  const [loginForm] = Form.useForm();

  useEffect(() => {
    if (remember.isRemembered()) {
      loginForm.setFieldsValue({ username: remember.getSavedUsername() });
    }
  }, [loginForm, remember]);

  const handleLogin = async (values: { username: string; password: string }) => {
    if (loading) return;
    setLoading(true);
    setError(null);
    setServerDown(false);
    try {
      await authLogin(values);
      remember.persist(values.username, rememberMe);
      message.success(`登录成功，欢迎 ${values.username}`);
      props.onLogin?.();
    } catch (err: unknown) {
      const axiosErr = err as { code?: string; message?: string; response?: { status?: number; data?: { detail?: string } } };
      if (axiosErr?.code === 'ERR_NETWORK' || axiosErr?.code === 'ECONNREFUSED' || String(axiosErr?.message || '').includes('Network')) {
        setServerDown(true);
        setError('无法连接到服务器，请检查服务是否已启动');
      } else if (axiosErr?.response?.status === 401) {
        setError('用户名或密码错误');
      } else {
        setError(getErrorMessage(err, '登录失败'));
      }
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (values: { username: string; password: string; company?: string; email?: string }) => {
    if (regLoading) return;
    setRegLoading(true);
    setError(null);
    try {
      const data = await registerUser(values);
      localStorage.setItem('token', data.access_token);
      remember.persist(data.username || '', false);
      message.success(`注册成功，欢迎 ${data.username}`);
      props.onLogin?.();
    } catch (err: unknown) {
      setError(getErrorMessage(err, '注册失败'));
    } finally {
      setRegLoading(false);
    }
  };

  const loginFormContent = loading ? (
    <div style={{ textAlign: 'center', padding: '40px 0' }}>
      <Spin size="large" />
      <div style={{ marginTop: 12, color: 'var(--color-text-secondary)' }}>登录中...</div>
    </div>
  ) : (
    <Form form={loginForm} onFinish={handleLogin} size="large">
      <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
        <Input prefix={<UserOutlined />} placeholder="用户名" disabled={serverDown} />
      </Form.Item>
      <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
        <Input.Password prefix={<LockOutlined />} placeholder="密码" disabled={serverDown} />
      </Form.Item>
      <Form.Item style={{ marginBottom: 4 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Checkbox checked={rememberMe} onChange={(e) => setRememberMe(e.target.checked)}>记住账号</Checkbox>
          <Button type="link" size="small" onClick={() => navigate('/forgot-password')} style={{ padding: 0 }}>忘记密码?</Button>
        </div>
      </Form.Item>
      <Form.Item style={{ marginBottom: 0 }}>
        <Button type="primary" htmlType="submit" loading={loading} block disabled={serverDown}>登录</Button>
      </Form.Item>
    </Form>
  );

  const registerFormContent = (
    <Form onFinish={handleRegister} size="large">
      <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
        <Input prefix={<UserOutlined />} placeholder="用户名" />
      </Form.Item>
      <Form.Item name="password" rules={[{ required: true, min: 6, message: '密码至少6位' }]}>
        <Input.Password prefix={<LockOutlined />} placeholder="密码" />
      </Form.Item>
      <Form.Item name="company"><Input prefix={<TeamOutlined />} placeholder="单位名称（选填）" /></Form.Item>
      <Form.Item name="email"><Input prefix={<MailOutlined />} placeholder="邮箱（选填）" /></Form.Item>
      <Form.Item style={{ marginBottom: 0 }}>
        <Button type="primary" htmlType="submit" loading={regLoading} block>注册并登录</Button>
      </Form.Item>
    </Form>
  );

  return (
    <div className="login-bg">
      <div className="login-card-wrapper fade-in">
        <Card style={{ width: 400, maxWidth: '100%', borderRadius: 12, boxShadow: '0 4px 24px rgba(0,0,0,0.25)' }}
          styles={{ body: { padding: '40px 32px' } }}>
          <div style={{ textAlign: 'center', marginBottom: 32 }}>
            <ProfileOutlined style={{ fontSize: 36, color: 'var(--color-brand)' }} />
            <Typography.Title level={3} style={{ margin: '12px 0 4px', color: 'var(--color-text)', fontSize: 20 }}>包合规</Typography.Title>
            <Typography.Text style={{ color: 'var(--color-text-secondary)', fontSize: 14 }}>招标文件合规自检系统</Typography.Text>
          </div>
          {serverDown && (
            <Alert message="无法连接服务器"
              description={<div><p>请确认以下服务已启动：</p><ol style={{ paddingLeft: 20, margin: '8px 0' }}><li>后端服务：<code>uv run uvicorn app.main:app --reload</code></li><li>数据库：<code>docker compose up -d db</code></li></ol><Button size="small" icon={<ReloadOutlined />} onClick={() => setServerDown(false)}>重试</Button></div>}
              type="error" showIcon style={{ marginBottom: 16, borderRadius: 8 }} />
          )}
          {error && !serverDown && (
            <Alert message={error} type="warning" showIcon closable onClose={() => setError(null)}
              style={{ marginBottom: 16, borderRadius: 8 }} />
          )}
          <Tabs activeKey={tab} onChange={setTab} centered size="large" items={[
            { key: 'login', label: '登录', children: loginFormContent },
            { key: 'register', label: '注册试用', children: registerFormContent },
          ]} />
          {tab === 'login' && (
            <div style={{ textAlign: 'center', marginTop: 12 }}>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>还没有账号? </Typography.Text>
              <Button type="link" size="small" onClick={() => setTab('register')} style={{ fontSize: 13 }}>立即注册</Button>
            </div>
          )}
          <Typography.Text style={{ display: 'block', textAlign: 'center', fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 8 }}>
            适用于招标代理机构和政府采购部门
          </Typography.Text>
        </Card>
      </div>
    </div>
  );
};

export default LoginPage;
