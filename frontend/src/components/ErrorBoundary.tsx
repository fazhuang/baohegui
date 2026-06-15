import React from 'react'
import { Result, Button } from 'antd'

interface Props {
  children: React.ReactNode
}

interface State {
  hasError: boolean
}

/**
 * ErrorBoundary — 全局异常边界
 *
 * 不泄漏堆栈信息，仅显示通用错误提示。
 * 提供"返回首页"和"重新加载"操作。
 */
class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(_error: Error): State {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return (
        <Result
          status="error"
          title="页面发生错误"
          subTitle="抱歉，页面发生了意外错误。请尝试刷新页面，或返回首页。"
          extra={
            <>
              <Button type="primary" onClick={() => {
                this.setState({ hasError: false })
                window.location.href = '/'
              }}>
                返回首页
              </Button>
              <Button onClick={() => {
                this.setState({ hasError: false })
                window.location.reload()
              }}>
                重新加载
              </Button>
            </>
          }
        />
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary
