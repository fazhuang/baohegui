/** 轻量日志工具 — 仅 dev 模式输出 */

// Vite 注入 import.meta.env.DEV，全局通过 Vite client types 声明
declare global {
  interface ImportMeta {
    readonly env: Record<string, string | boolean | undefined>;
  }
}

const isDev = import.meta.env?.DEV === true;

const _console = {
  info: (...args: unknown[]) => { if (isDev) console.info('[baohegui]', ...args) },
  warn: (...args: unknown[]) => { if (isDev) console.warn('[baohegui]', ...args) },
  error: (...args: unknown[]) => { if (isDev) console.error('[baohegui]', ...args) },
}

export const logger = _console

/** 安全错误消息提取 — 不泄漏内部堆栈 */
export function safeErrorMessage(err: unknown, fallback = '操作失败'): string {
  if (!err) return fallback
  if (typeof err === 'string') return err
  if (err instanceof Error) {
    // 类型安全的 axios 错误检查
    const axiosErr = err as { response?: { status?: number } }
    if (axiosErr.response?.status) {
      const s = axiosErr.response.status
      if (s === 401) return '登录已过期，请重新登录'
      if (s === 403) return '无权访问'
      if (s === 404) return '资源不存在'
      if (s >= 500) return '服务器错误，请稍后重试'
    }
    return err.message || fallback
  }
  return fallback
}
