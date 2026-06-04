import React, { useState } from 'react'
import { Card, Form, Input, Button, Typography, message, Alert, Spin, Tabs } from 'antd'
import { UserOutlined, LockOutlined, ReloadOutlined, TeamOutlined, MailOutlined, ProfileOutlined } from '@ant-design/icons'
import axios from 'axios'
import { useNavigate } from 'react-router-dom'
import { registerUser } from '../services/api'

interface LoginProps { onLogin?: () => void }

const LoginPage: React.FC<LoginProps> = (props) => {
  const [loading, setLoading] = useState(false)
  const [regLoading, setRegLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [serverDown, setServerDown] = useState(false)
  const [tab, setTab] = useState('login')
  const navigate = useNavigate()

  const handleLogin = async (values: { username: string; password: string }) => {
    setLoading(true)
    setError(null)
    setServerDown(false)

    try {
      const { data } = await axios.post('/api/auth/login', values)
      localStorage.setItem('token', data.access_token)
      localStorage.setItem('role', data.role || 'user')
      localStorage.setItem('username', data.username || '')
      message.success(`登录成功，欢迎 ${data.username}`)
      props.onLogin?.(); return
    } catch (err: any) {
      if (err.code === 'ERR_NETWORK' || err.code === 'ECONNREFUSED' || err.message?.includes('Network')) {
        setServerDown(true)
        setError('无法连接到服务器，请检查服务是否已启动')
      } else if (err.response?.status === 401) {
        setError('用户名或密码错误')
      } else {
        setError(err?.response?.data?.detail || err.message || '登录失败')
      }
    }
    setLoading(false)
  }

  const handleRegister = async (values: any) => {
    setRegLoading(true)
    setError(null)
    try {
      const data = await registerUser(values)
      localStorage.setItem('token', data.access_token)
      localStorage.setItem('role', data.role)
      localStorage.setItem('username', data.username)
      message.success(`注册成功，欢迎 ${data.username}`)
      props.onLogin?.(); return
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || '注册失败')
    }
    setRegLoading(false)
  }

  // 开发模式快速进入
  const handleDevLogin = () => {
    localStorage.setItem('token', 'dev-token')
    localStorage.setItem('role', 'admin')
    localStorage.setItem('username', 'dev')
    message.success('开发模式 - 已自动登录（管理员权限）')
    navigate('/')
  }

  return (
    <div className="login-bg">
      <Card
        style={{
          width: 400,
          maxWidth: '100%',
          borderRadius: 12,
          boxShadow: '0 4px 24px rgba(0,0,0,0.25)',
        }}
        styles={{ body: { padding: '40px 32px' } }}
      >
        {/* Logo Area */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <ProfileOutlined
            style={{ fontSize: 36, color: 'var(--color-brand)' }}
          />
          <Typography.Title
            level={3}
            style={{ margin: '12px 0 4px', color: 'var(--color-text)', fontSize: 20 }}
          >
            包合规
          </Typography.Title>
          <Typography.Text style={{ color: 'var(--color-text-secondary)', fontSize: 14 }}>
            招标文件合规自检系统
          </Typography.Text>
        </div>

        {/* 服务器不可用提示 */}
        {serverDown && (
          <Alert
            message="无法连接服务器"
            description={
              <div>
                <p>请确认以下服务已启动：</p>
                <ol style={{ paddingLeft: 20, margin: '8px 0' }}>
                  <li>后端服务：<code>uv run uvicorn app.main:app --reload</code></li>
                  <li>数据库：<code>docker compose up -d db</code></li>
                </ol>
                <Button size="small" icon={<ReloadOutlined />} onClick={() => setServerDown(false)}>
                  重试
                </Button>
              </div>
            }
            type="error"
            showIcon
            style={{ marginBottom: 16, borderRadius: 8 }}
          />
        )}

        {/* 登录错误提示 */}
        {error && !serverDown && (
          <Alert
            message={error}
            type="warning"
            showIcon
            closable
            onClose={() => setError(null)}
            style={{ marginBottom: 16, borderRadius: 8 }}
          />
        )}

        <Tabs activeKey={tab} onChange={setTab} centered size="large" items={[
          {
            key: 'login',
            label: '登录',
            children: loading ? (
              <div style={{ textAlign: 'center', padding: '40px 0' }}>
                <Spin size="large" />
                <div style={{ marginTop: 12, color: 'var(--color-text-secondary)' }}>登录中...</div>
              </div>
            ) : (
              <Form onFinish={handleLogin} size="large">
                <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                  <Input prefix={<UserOutlined />} placeholder="用户名" disabled={serverDown} />
                </Form.Item>
                <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
                  <Input.Password prefix={<LockOutlined />} placeholder="密码" disabled={serverDown} />
                </Form.Item>
                <Form.Item style={{ marginBottom: 0 }}>
                  <Button type="primary" htmlType="submit" loading={loading} block disabled={serverDown}>
                    登录
                  </Button>
                </Form.Item>
              </Form>
            )
          },
          {
            key: 'register',
            label: '注册试用',
            children: (
              <Form onFinish={handleRegister} size="large">
                <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                  <Input prefix={<UserOutlined />} placeholder="用户名" />
                </Form.Item>
                <Form.Item name="password" rules={[{ required: true, min: 6, message: '密码至少6位' }]}>
                  <Input.Password prefix={<LockOutlined />} placeholder="密码" />
                </Form.Item>
                <Form.Item name="company">
                  <Input prefix={<TeamOutlined />} placeholder="单位名称（选填）" />
                </Form.Item>
                <Form.Item name="email">
                  <Input prefix={<MailOutlined />} placeholder="邮箱（选填）" />
                </Form.Item>
                <Form.Item style={{ marginBottom: 0 }}>
                  <Button type="primary" htmlType="submit" loading={regLoading} block>
                    注册并登录
                  </Button>
                </Form.Item>
              </Form>
            )
          }
        ]} />

        {/* 用户范围说明 */}
        <Typography.Text
          style={{
            display: 'block',
            textAlign: 'center',
            fontSize: 12,
            color: 'var(--color-text-tertiary)',
            marginTop: 8,
          }}
        >
          适用于招标代理机构和政府采购部门
        </Typography.Text>

        {/* 开发模式入口 */}
        <div style={{
          textAlign: 'center',
          borderTop: '1px solid var(--color-border)',
          paddingTop: 16,
          marginTop: 16,
        }}>
          <Button type="link" size="small" onClick={handleDevLogin} style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            开发模式 · 一键登录
          </Button>
        </div>
      </Card>
    </div>
  )
}

export default LoginPage
