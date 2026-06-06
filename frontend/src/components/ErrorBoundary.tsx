import React from 'react'
import { Result, Button } from 'antd'

interface Props {
  children: React.ReactNode
}

interface State {
  hasError: boolean
  error?: Error
}

class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      return (
        <Result
          status="error"
          title="页面发生错误"
          subTitle={this.state.error?.message}
          extra={
            <Button type="primary" onClick={() => {
              this.setState({ hasError: false })
              window.location.reload()
            }}>
              刷新页面
            </Button>
          }
        />
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary
