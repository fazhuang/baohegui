import React, { useState } from 'react'
import { Card, Form, Input, Button, Typography, message, Alert, Result } from 'antd'
import { LockOutlined, ArrowLeftOutlined, ProfileOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { resetPassword } from '../services/api'

const ResetPassword: React.FC = () => {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (values: { password: string }) => {
    if (!token) {
      setError('重置链接无效或已过期')
      return
    }
    setLoading(true)
    setError(null)
    try {
      await resetPassword(token, values.password)
      setDone(true)
      message.success('密码已重置，请使用新密码登录')
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || '重置失败')
    }
    setLoading(false)
  }

  return (
    <div className="login-bg">
      <div className="login-card-wrapper fade-in">
        <Card
          style={{ width: 400, maxWidth: '100%', borderRadius: 12, boxShadow: '0 4px 24px rgba(0,0,0,0.25)' }}
          styles={{ body: { padding: '40px 32px' } }}
        >
          {/* Logo */}
          <div style={{ textAlign: 'center', marginBottom: 32 }}>
            <ProfileOutlined style={{ fontSize: 36, color: 'var(--color-brand)' }} />
            <Typography.Title level={3} style={{ margin: '12px 0 4px', color: 'var(--color-text)', fontSize: 20 }}>
              设置新密码
            </Typography.Title>
            <Typography.Text style={{ color: 'var(--color-text-secondary)', fontSize: 14 }}>
              请输入您的新密码
            </Typography.Text>
          </div>

          {error && (
            <Alert message={error} type="warning" showIcon closable onClose={() => setError(null)}
              style={{ marginBottom: 16, borderRadius: 8 }} />
          )}

          {!token && !done ? (
            <Alert
              message="无效链接"
              description="密码重置链接无效或已过期，请重新申请"
              type="error"
              showIcon
              style={{ marginBottom: 16, borderRadius: 8 }}
              action={<Button size="small" onClick={() => navigate('/forgot-password')}>重新申请</Button>}
            />
          ) : done ? (
            <Result
              status="success"
              title="密码重置成功"
              subTitle="请使用新密码登录"
              extra={[
                <Button key="login" type="primary" onClick={() => navigate('/login')}>
                  去登录
                </Button>,
              ]}
            />
          ) : (
            <Form onFinish={handleSubmit} size="large">
              <Form.Item name="password" rules={[
                { required: true, message: '请输入新密码' },
                { min: 6, message: '密码至少6位' },
              ]}>
                <Input.Password prefix={<LockOutlined />} placeholder="新密码" />
              </Form.Item>
              <Form.Item name="confirmPassword" rules={[
                { required: true, message: '请确认新密码' },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    if (!value || getFieldValue('password') === value) {
                      return Promise.resolve()
                    }
                    return Promise.reject(new Error('两次输入的密码不一致'))
                  },
                }),
              ]}>
                <Input.Password prefix={<LockOutlined />} placeholder="确认新密码" />
              </Form.Item>
              <Form.Item style={{ marginBottom: 0 }}>
                <Button type="primary" htmlType="submit" loading={loading} block>
                  重置密码
                </Button>
              </Form.Item>
              <div style={{ textAlign: 'center', marginTop: 16 }}>
                <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/login')}>
                  返回登录
                </Button>
              </div>
            </Form>
          )}
        </Card>
      </div>
    </div>
  )
}

export default ResetPassword
