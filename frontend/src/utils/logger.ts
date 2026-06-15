const isDev = typeof import.meta !== 'undefined' && (import.meta as any).env?.DEV

const _console = {
  info: (...args: unknown[]) => { if (isDev) console.info('[baohegui]', ...args) },
  warn: (...args: unknown[]) => { if (isDev) console.warn('[baohegui]', ...args) },
  error: (...args: unknown[]) => { if (isDev) console.error('[baohegui]', ...args) },
}

export const logger = _console

export function safeErrorMessage(err: unknown, fallback = '操作失败'): string {
  if (!err) return fallback
  if (typeof err === 'string') return err
  if (err instanceof Error) {
    const anyErr = err as any
    if (anyErr.response?.status) {
      const s = anyErr.response.status
      if (s === 401) return '登录已过期，请重新登录'
      if (s === 403) return '无权访问'
      if (s === 404) return '资源不存在'
      if (s >= 500) return '服务器错误，请稍后重试'
    }
    return err.message || fallback
  }
  return fallback
}
