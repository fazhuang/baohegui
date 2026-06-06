import React, { useState } from 'react'
import { Card, Form, Input, Button, Typography, message, Alert, Result } from 'antd'
import { MailOutlined, ArrowLeftOutlined, ProfileOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { forgotPassword } from '../services/api'

const ForgotPassword: React.FC = () => {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (values: { email: string }) => {
    setLoading(true)
    setError(null)
    try {
      await forgotPassword(values.email)
      setSent(true)
      message.success('重置链接已发送，请检查邮箱')
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || '发送失败')
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
              重置密码
            </Typography.Title>
            <Typography.Text style={{ color: 'var(--color-text-secondary)', fontSize: 14 }}>
              请输入注册邮箱，我们将发送重置链接
            </Typography.Text>
          </div>

          {error && (
            <Alert message={error} type="warning" showIcon closable onClose={() => setError(null)}
              style={{ marginBottom: 16, borderRadius: 8 }} />
          )}

          {sent ? (
            <Result
              status="success"
              title="邮件已发送"
              subTitle="请检查您的邮箱，点击邮件中的链接重置密码"
              extra={[
                <Button key="back" icon={<ArrowLeftOutlined />} onClick={() => navigate('/login')}>
                  返回登录
                </Button>,
              ]}
            />
          ) : (
            <Form onFinish={handleSubmit} size="large">
              <Form.Item name="email" rules={[
                { required: true, message: '请输入邮箱地址' },
                { type: 'email', message: '请输入有效的邮箱地址' },
              ]}>
                <Input prefix={<MailOutlined />} placeholder="注册邮箱" />
              </Form.Item>
              <Form.Item style={{ marginBottom: 0 }}>
                <Button type="primary" htmlType="submit" loading={loading} block>
                  发送重置链接
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

export default ForgotPassword
