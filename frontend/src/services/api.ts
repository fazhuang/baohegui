/**
 * API 服务层
 *
 * 所有 API 函数统一通过 services/http.ts 发起请求。
 * 页面/组件禁止直接使用 axios.get / axios.post / fetch。
 */

import http, { downloadBlob } from './http';
import type {
  ReportListResponse,
  PlatformRule, RuleListResponse, SyncResultData, SyncHistoryItem,
  SyncStatus, DashboardStats, EngineStatus, BillingStatus,
  ComplianceReport, MemberDashboardResponse,
} from '../types';
import type { UserInfo, AuditLogEntry, CompareResult } from '../types/admin-types';

// ═══════════════════════════════════════════════════════════════
// Auth
// ═══════════════════════════════════════════════════════════════

export interface LoginParams {
  username: string;
  password: string;
}

export interface LoginResult {
  access_token: string;
  token_type: string;
  user_id: number;
  username: string;
  role: string;
  company: string;
}

export interface CurrentUserResponse {
  user_id: number;
  username: string;
  role: string;
  company: string;
  email: string;
  permissions: string[];
}

export async function loginUser(params: LoginParams): Promise<LoginResult> {
  const { data } = await http.post('/auth/login', params);
  return data;
}

export async function registerUser(params: {
  username: string; password: string; company?: string; email?: string;
}): Promise<LoginResult> {
  const { data } = await http.post('/auth/register', params);
  return data;
}

export async function getCurrentUser(): Promise<CurrentUserResponse> {
  const { data } = await http.get('/auth/me');
  return data;
}

export async function forgotPassword(email: string): Promise<{ message: string }> {
  const { data } = await http.post('/auth/forgot-password', { email });
  return data;
}

export async function resetPassword(token: string, new_password: string): Promise<{ message: string }> {
  const { data } = await http.post('/auth/reset-password', { token, new_password });
  return data;
}

// ═══════════════════════════════════════════════════════════════
// Upload
// ═══════════════════════════════════════════════════════════════

export async function uploadFile(file: File): Promise<{
  file_id: string; db_id: number; filename: string; page_count: number;
  sections: Record<string, string>; industry?: string[] | null;
}> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await http.post('/upload/', form);
  return data;
}

export async function getUploadStatus(fileId: number): Promise<{
  stage: string; bytes_read?: number; filename?: string; file_size?: number; error?: string;
}> {
  const { data } = await http.get(`/upload/${fileId}/status`);
  return data;
}

// ═══════════════════════════════════════════════════════════════
// Check
// ═══════════════════════════════════════════════════════════════

export async function runCheck(fileId: number): Promise<{
  report_id: number; total_score: number; total_violations: number;
  high_risk_count: number; medium_risk_count: number; low_risk_count: number;
  section_score: number; keyword_score: number; forbidden_score: number;
  semantic_score: number; llm_model_used: string; llm_tokens_used: number;
  llm_cost_yuan: number; llm_error: string | null; industries?: string[] | null;
  traffic_light?: string; routing_reasoning?: string; parameter_bias_score?: number;
  parameter_bias_findings?: number; merge_risk_level?: string;
  merge_review_status?: string; merge_requires_human_review?: boolean;
  merge_confirmed_count?: number; merge_high_risk_count?: number;
}> {
  const { data } = await http.post(`/check/${fileId}`);
  return data;
}

export async function getCheckStatus(fileId: number): Promise<{
  stage: string; file_id?: number; report_id?: number; error?: string;
}> {
  const { data } = await http.get(`/check/${fileId}/status`);
  return data;
}

// ═══════════════════════════════════════════════════════════════
// Report
// ═══════════════════════════════════════════════════════════════

export async function getReport(reportId: number): Promise<ComplianceReport> {
  const { data } = await http.get(`/report/${reportId}`);
  return data;
}

export async function getReportPdfUrl(reportId: number): Promise<string> {
  return downloadBlob(`/api/report/${reportId}/pdf`);
}

export async function getReportExcelUrl(reportId: number): Promise<string> {
  return downloadBlob(`/api/report/${reportId}/export`);
}

export async function listReports(params?: {
  search?: string; date_from?: string; date_to?: string;
  score_min?: number; score_max?: number; sort_by?: string;
  sort_order?: string; page?: number; page_size?: number;
}): Promise<ReportListResponse> {
  const { data } = await http.get('/report/list/', { params });
  return data;
}

export async function submitFeedback(params: {
  report_id: number; rule_id: string; content: string;
}): Promise<{ message: string }> {
  const { data } = await http.post('/report/feedback', params);
  return data;
}

// ═══════════════════════════════════════════════════════════════
// Rules
// ═══════════════════════════════════════════════════════════════

export async function getEngineStatus(): Promise<{ total: number; by_type: Record<string, number> }> {
  const { data } = await http.get('/rules/engine/status');
  return data;
}

export async function listPlatformRules(params?: {
  search?: string; platform?: string; enabled_only?: boolean;
}): Promise<RuleListResponse> {
  const { data } = await http.get('/rules/platform/list', { params });
  return data;
}

export async function getPlatformRule(ruleId: string): Promise<PlatformRule> {
  const { data } = await http.get(`/rules/platform/${ruleId}`);
  return data;
}

export async function createPlatformRule(rule: Partial<PlatformRule>): Promise<PlatformRule> {
  const { data } = await http.post('/rules/platform', rule);
  return data.rule;
}

export async function updatePlatformRule(ruleId: string, updates: Partial<PlatformRule>): Promise<PlatformRule> {
  const { data } = await http.put(`/rules/platform/${ruleId}`, updates);
  return data.rule;
}

export async function deletePlatformRule(ruleId: string): Promise<void> {
  await http.delete(`/rules/platform/${ruleId}`);
}

export async function togglePlatformRule(ruleId: string): Promise<boolean> {
  const { data } = await http.post(`/rules/platform/${ruleId}/toggle`);
  return data.enabled;
}

export async function reloadRules(): Promise<{ rule_count: number }> {
  const { data } = await http.post('/rules/reload');
  return data;
}

export async function importRules(rules: PlatformRule[]): Promise<{ status: string; imported: number }> {
  const { data } = await http.post('/rules/import', { rules });
  return data;
}

export async function getSyncStatus(): Promise<SyncStatus> {
  const { data } = await http.get('/rules/sync/status');
  return data;
}

export async function runSync(platform: string): Promise<SyncResultData> {
  const { data } = await http.post('/rules/sync/run', null, { params: { platform } });
  return data;
}

export async function getSyncHistory(): Promise<SyncHistoryItem[]> {
  const { data } = await http.get('/rules/sync/history');
  return data;
}

export async function getRulesStats(): Promise<EngineStatus> {
  const { data } = await http.get('/rules/stats');
  return data;
}

export async function getRuleEffectiveness(): Promise<{ rules: PlatformRule[]; total_reports: number }> {
  const { data } = await http.get('/rules/effectiveness');
  return data;
}

export async function getRuleVersions(): Promise<{ versions: { filename: string; timestamp: string; rule_count: number }[] }> {
  const { data } = await http.get('/rules/versions');
  return data;
}

export async function rollbackVersion(filename: string): Promise<{ status: string; message: string }> {
  const { data } = await http.post('/rules/versions/rollback', { filename });
  return data;
}

export async function batchToggleRules(ruleIds: string[], enabled: boolean): Promise<{ status: string; toggled: number }> {
  const { data } = await http.post('/rules/batch/toggle', { rule_ids: ruleIds, enabled });
  return data;
}

export async function fetchAllRules(search?: string): Promise<{ total: number; rules: PlatformRule[] }> {
  const { data } = await http.get('/rules/platform/list', { params: search ? { search } : {} });
  return data;
}

// ═══════════════════════════════════════════════════════════════
// Admin
// ═══════════════════════════════════════════════════════════════

export async function listUsers(): Promise<UserInfo[]> {
  const { data } = await http.get('/admin/users');
  return data;
}

export async function createUser(req: { username: string; password: string; role?: string; company?: string; email?: string }): Promise<{ message: string; user_id: number }> {
  const { data } = await http.post('/admin/users', req);
  return data;
}

export async function updateUser(userId: number, updates: { password?: string; role?: string; company?: string; email?: string; is_active?: boolean }): Promise<{ message: string }> {
  const { data } = await http.put(`/admin/users/${userId}`, updates);
  return data;
}

export async function deleteUser(userId: number): Promise<{ message: string }> {
  const { data } = await http.delete(`/admin/users/${userId}`);
  return data;
}

export async function listAuditLogs(params?: { user_id?: number; limit?: number }): Promise<{ total: number; logs: AuditLogEntry[] }> {
  const { data } = await http.get('/admin/audit', { params });
  return data;
}

export async function compareFiles(fileA: number, fileB: number): Promise<CompareResult> {
  const { data } = await http.get('/admin/compare', { params: { file_a: fileA, file_b: fileB } });
  return data;
}

export async function getBillingThreshold(): Promise<{ max_monthly_tokens: number; max_monthly_cost_yuan: number; alert_threshold_pct: number }> {
  const { data } = await http.get('/admin/billing/threshold');
  return data;
}

export async function setBillingThreshold(req: { max_monthly_tokens: number; max_monthly_cost_yuan: number; alert_threshold_pct: number }): Promise<{ message: string }> {
  const { data } = await http.put('/admin/billing/threshold', req);
  return data;
}

export async function getBillingStatus(): Promise<BillingStatus> {
  const { data } = await http.get('/admin/billing/status');
  return data;
}

// ═══════════════════════════════════════════════════════════════
// Stats
// ═══════════════════════════════════════════════════════════════

export async function getDashboardStats(): Promise<DashboardStats> {
  const { data } = await http.get('/stats/dashboard');
  return data;
}

// ═══════════════════════════════════════════════════════════════
// Member
// ═══════════════════════════════════════════════════════════════

export async function getMemberDashboard(): Promise<MemberDashboardResponse> {
  const { data } = await http.get('/member/dashboard');
  return data;
}

// ═══════════════════════════════════════════════════════════════
// Announcements
// ═══════════════════════════════════════════════════════════════

export async function listAnnouncements(params?: { limit?: number }): Promise<Array<{
  id: number; title: string; summary: string; severity: string; source: string;
  published_at: string; created_at: string; content?: string; url?: string;
}>> {
  const { data } = await http.get('/announcements', { params });
  return data;
}
