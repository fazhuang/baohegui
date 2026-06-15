import axios from 'axios'
import type {
  BillingStatus,
  CheckProgress,
  CheckResult,
  ComplianceReport,
  CreateUserRequest,
  ReportListResponse,
  UpdateUserRequest,
  UploadProgress,
  UploadResult,
} from '../types'

const api = axios.create({
  baseURL: '/api',
  timeout: 300000, // 5分钟
})

// 请求拦截器 - 添加认证
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      // 使用 root path 而非 /login 避免 Vercel SPA 硬导航 404
      window.location.href = '/'
    }
    return Promise.reject(error)
  }
)

/** 上传文件 */
export async function uploadFile(file: File): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post('/upload/', form)
  return data
}

/** 获取上传进度 */
export async function getUploadStatus(fileId: number): Promise<UploadProgress> {
  const { data } = await api.get(`/upload/${fileId}/status`)
  return data
}

/** 获取检查进度 */
export async function getCheckStatus(fileId: number): Promise<CheckProgress> {
  const { data } = await api.get(`/check/${fileId}/status`)
  return data
}

/** 执行合规检查 */
export async function runCheck(fileId: number): Promise<CheckResult> {
  const { data } = await api.post(`/check/${fileId}`)
  return data
}

/** 获取报告详情 */
export async function getReport(reportId: number): Promise<ComplianceReport> {
  const { data } = await api.get(`/report/${reportId}`)
  return data
}

/** 下载报告 PDF — 返回 blob URL 用于 <a> download */
export async function getReportPdfUrl(reportId: number): Promise<string> {
  const token = localStorage.getItem('token')
  const resp = await fetch(`/api/report/${reportId}/pdf`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!resp.ok) {
    if (resp.status === 401 || resp.status === 403) {
      throw new Error('无权访问此报告')
    }
    throw new Error(`下载失败: ${resp.status}`)
  }
  const blob = await resp.blob()
  return URL.createObjectURL(blob)
}

/** 导出报告 Excel — 返回 blob URL 用于 <a> download */
export async function getReportExcelUrl(reportId: number): Promise<string> {
  const token = localStorage.getItem('token')
  const resp = await fetch(`/api/report/${reportId}/export`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!resp.ok) {
    if (resp.status === 401 || resp.status === 403) {
      throw new Error('无权访问此报告')
    }
    throw new Error(`下载失败: ${resp.status}`)
  }
  const blob = await resp.blob()
  return URL.createObjectURL(blob)
}

/** 列出历史报告 */
export async function listReports(params?: {
  search?: string
  date_from?: string
  date_to?: string
  score_min?: number
  score_max?: number
  sort_by?: string
  sort_order?: string
  page?: number
  page_size?: number
}): Promise<ReportListResponse> {
  const { data } = await api.get('/report/list/', { params })
  return data
}

/** ── 管理员后台 API ──────────────────────────────── */

import type {
  PlatformRule, RuleListResponse, SyncResultData,
  SyncHistoryItem, SyncStatus, EngineStatus,
} from '../types'

/** 规则引擎状态 */
export async function getEngineStatus(): Promise<EngineStatus> {
  const { data } = await api.get('/rules/engine/status')
  return data
}

/** 规则列表 */
export async function listPlatformRules(params?: {
  search?: string; platform?: string; enabled_only?: boolean
}): Promise<RuleListResponse> {
  const { data } = await api.get('/rules/platform/list', { params })
  return data
}

/** 获取单条规则 */
export async function getPlatformRule(ruleId: string): Promise<PlatformRule> {
  const { data } = await api.get(`/rules/platform/${ruleId}`)
  return data
}

/** 创建规则 */
export async function createPlatformRule(rule: Partial<PlatformRule>): Promise<PlatformRule> {
  const { data } = await api.post('/rules/platform', rule)
  return data.rule
}

/** 更新规则 */
export async function updatePlatformRule(ruleId: string, updates: Partial<PlatformRule>): Promise<PlatformRule> {
  const { data } = await api.put(`/rules/platform/${ruleId}`, updates)
  return data.rule
}

/** 删除规则 */
export async function deletePlatformRule(ruleId: string): Promise<void> {
  await api.delete(`/rules/platform/${ruleId}`)
}

/** 切换启用/停用 */
export async function togglePlatformRule(ruleId: string): Promise<boolean> {
  const { data } = await api.post(`/rules/platform/${ruleId}/toggle`)
  return data.enabled
}

/** 热加载规则 */
export async function reloadRules(): Promise<{ rule_count: number }> {
  const { data } = await api.post('/rules/reload')
  return data
}

/** 导入规则 */
export async function importRules(rules: Partial<PlatformRule>[]): Promise<SyncResultData> {
  const { data } = await api.post('/rules/import', { rules })
  return data
}

/** 同步状态 */
export async function getSyncStatus(): Promise<SyncStatus> {
  const { data } = await api.get('/rules/sync/status')
  return data
}

/** 执行同步 */
export async function runSync(platform: string): Promise<SyncResultData> {
  const { data } = await api.post('/rules/sync/run', null, { params: { platform } })
  return data
}

/** 同步历史 */
export async function getSyncHistory(): Promise<SyncHistoryItem[]> {
  const { data } = await api.get('/rules/sync/history')
  return data
}

/** 获取当前用户信息 */
export async function getCurrentUser(): Promise<{ user_id: number; username: string; role: string; company: string; email: string; permissions: string[] }> {
  const { data } = await api.get('/auth/me')
  return data
}

/** 用户注册 */
export async function registerUser(params: {
  username: string; password: string; company?: string; email?: string
}): Promise<{ access_token: string; user_id: number; username: string; role: string }> {
  const { data } = await api.post('/auth/register', params)
  return data
}

/** ── 统计看板 ──────────────────────────────────────── */

import type { DashboardStats } from '../types'
export type { DashboardStats }

export async function getDashboardStats(): Promise<DashboardStats> {
  const { data } = await api.get('/stats/dashboard')
  return data
}

/** ── 管理后台 API ─────────────────────────────────── */

export interface UserInfo {
  id: number
  username: string
  role: string
  company: string
  email: string
  is_active: boolean
  created_at: string | null
}

export interface AuditLogEntry {
  id: number
  user_id: number
  action: string
  resource: string | null
  resource_id: string | null
  detail: string | null
  ip_address: string | null
  created_at: string | null
}

export interface CompareResult {
  info: {
    file_a: { id: number; filename: string; file_size: number; page_count: number; file_hash: string; status: string }
    file_b: { id: number; filename: string; file_size: number; page_count: number; file_hash: string; status: string }
    is_same_file: boolean
  }
  section_diff: { both: string[]; only_in_a: string[]; only_in_b: string[] }
  score_diff: Record<string, { a: number; b: number; delta?: number }> | null
}

export async function listUsers(): Promise<UserInfo[]> {
  const { data } = await api.get('/admin/users')
  return data
}

export async function createUser(req: CreateUserRequest): Promise<{ message: string; user_id: number }> {
  const { data } = await api.post('/admin/users', req)
  return data
}

export async function updateUser(userId: number, updates: UpdateUserRequest): Promise<{ message: string }> {
  const { data } = await api.put(`/admin/users/${userId}`, updates)
  return data
}

export async function deleteUser(userId: number): Promise<{ message: string }> {
  const { data } = await api.delete(`/admin/users/${userId}`)
  return data
}

export async function listAuditLogs(params?: { user_id?: number; limit?: number }): Promise<{ total: number; logs: AuditLogEntry[] }> {
  const { data } = await api.get('/admin/audit', { params })
  return data
}

export async function compareFiles(fileA: number, fileB: number): Promise<CompareResult> {
  const { data } = await api.get('/admin/compare', { params: { file_a: fileA, file_b: fileB } })
  return data
}

export async function getBillingThreshold(): Promise<{ max_monthly_tokens: number; max_monthly_cost_yuan: number; alert_threshold_pct: number }> {
  const { data } = await api.get('/admin/billing/threshold')
  return data
}

export async function setBillingThreshold(req: { max_monthly_tokens: number; max_monthly_cost_yuan: number; alert_threshold_pct: number }): Promise<{ message: string }> {
  const { data } = await api.put('/admin/billing/threshold', req)
  return data
}

export async function getBillingStatus(): Promise<BillingStatus> {
  const { data } = await api.get('/admin/billing/status')
  return data
}

/** 发送密码重置邮件 */
export async function forgotPassword(email: string): Promise<{ message: string }> {
  const { data } = await api.post('/auth/forgot-password', { email })
  return data
}

/** 重置密码 */
export async function resetPassword(token: string, new_password: string): Promise<{ message: string }> {
  const { data } = await api.post('/auth/reset-password', { token, new_password })
  return data
}

export default api
