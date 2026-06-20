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
  ComplaintCaseItem, ComplaintCaseDetail, ReviewQueueStats,
  ReviewActionResponse, CandidateRuleItem, CandidateRuleDetail,
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

// ═══════════════════════════════════════════════════════════════
// Knowledge Graph
// ═══════════════════════════════════════════════════════════════

export interface KGNode {
  id: number;
  node_type: 'regulation' | 'case' | 'rule' | 'template' | 'concept';
  title: string;
  content: string;
  source: string;
  source_url?: string;
  tags: string;
  rule_id?: string | null;
  jurisdiction?: string;
  effective_date?: string | null;
  publish_date?: string | null;
  trust_level: number;
  audit_status: 'unreviewed' | 'verified' | 'flagged' | 'rejected';
  created_at?: string;
}

export interface KGRelatedNode {
  relation: string;
  weight: number;
  node: {
    id: number;
    node_type: string;
    title: string;
    content: string;
    source: string;
    source_url?: string | null;
    rule_id?: string | null;
    tags: string;
    jurisdiction?: string | null;
    effective_date?: string | null;
    publish_date?: string | null;
    created_at?: string | null;
    trust_level: number;
    audit_status: string;
  };
}

export interface KGRagContext {
  type: 'regulation' | 'case';
  rule_id: string;
  title: string;
  content: string;
  source: string;
  source_url?: string | null;
  node_id: number;
  trust_level: number;
  effective_date?: string | null;
  publish_date?: string | null;
  relation?: string;
  edge_weight?: number;
}

export interface KGStats {
  total_nodes: number;
  by_type: Record<string, number>;
  by_audit_status: Record<string, number>;
  total_edges: number;
}

export interface KGSearchResult {
  query: string;
  results: KGNode[];
  total: number;
  limit: number;
  offset: number;
}

export async function searchKG(params: {
  q?: string;
  node_type?: string;
  min_trust?: number;
  audit_status?: string;
  tags?: string;
  rule_id?: string;
  jurisdiction?: string;
  limit?: number;
  offset?: number;
}): Promise<KGSearchResult> {
  const { data } = await http.get('/kg/search', { params });
  return data;
}

export async function getRelatedNodes(nodeId: number, relation?: string, direction?: string): Promise<{ related: KGRelatedNode[] }> {
  const { data } = await http.get(`/kg/related/${nodeId}`, { params: { ...(relation ? { relation } : {}), ...(direction ? { direction } : {}) } });
  return data;
}

export async function getRegulationForRule(ruleId: string): Promise<{ regulations: KGRelatedNode[] }> {
  const { data } = await http.get(`/kg/regulation/${ruleId}`);
  return data;
}

export async function getCasesForRule(ruleId: string): Promise<{ cases: KGRelatedNode[] }> {
  const { data } = await http.get(`/kg/cases/${ruleId}`);
  return data;
}

export async function getSimilarCases(desc: string, limit?: number): Promise<{ cases: KGNode[] }> {
  const { data } = await http.get('/kg/similar-cases', { params: { desc, limit: limit ?? 5 } });
  return data;
}

export async function getRagContext(ruleId: string, violationDesc?: string): Promise<{ contexts: KGRagContext[]; context_count: number }> {
  const { data } = await http.get('/kg/rag-context', { params: { rule_id: ruleId, violation_desc: violationDesc ?? '' } });
  return data;
}

export async function getKGStats(): Promise<KGStats> {
  const { data } = await http.get('/kg/stats');
  return data;
}

// Admin-only KG APIs
export async function seedKG(): Promise<{ status: string; count: number }> {
  const { data } = await http.post('/kg/seed');
  return data;
}

export async function createKGNode(node: {
  node_type: string;
  title: string;
  content: string;
  source?: string;
  source_url?: string;
  tags?: string;
  rule_id?: string | null;
  jurisdiction?: string;
  trust_level?: number;
  audit_status?: string;
}): Promise<{ id: number; title: string; node_type: string }> {
  const { data } = await http.post('/kg/node', node);
  return data;
}

export async function updateKGNode(nodeId: number, updates: Record<string, unknown>): Promise<{ id: number; updated_fields: string[] }> {
  const { data } = await http.put(`/kg/node/${nodeId}`, updates);
  return data;
}

export async function auditKGNode(nodeId: number, trustLevel: number, auditStatus: string): Promise<{ id: number; trust_level: number; audit_status: string }> {
  const { data } = await http.put(`/kg/node/${nodeId}/audit`, null, { params: { trust_level: trustLevel, audit_status: auditStatus } });
  return data;
}

export async function deleteKGNode(nodeId: number): Promise<{ status: string; id: number }> {
  const { data } = await http.delete(`/kg/node/${nodeId}`);
  return data;
}

export async function getNodesNeedingReview(): Promise<{ nodes: Array<{ id: number; node_type: string; title: string; source: string; rule_id?: string; trust_level: number; audit_status: string; content_preview: string }> }> {
  const { data } = await http.get('/kg/nodes/needing-review');
  return data;
}

// ═══════════════════════════════════════════════════════════════
// 案例审核管理 (Phase 2) — Admin only
// ═══════════════════════════════════════════════════════════════

export interface CaseReviewListResponse {
  total: number;
  limit: number;
  offset: number;
  cases: ComplaintCaseItem[];
}

export async function getReviewQueue(params: {
  review_status?: string;
  source_type?: string;
  province?: string;
  decision_type?: string;
  search?: string;
  limit?: number;
  offset?: number;
  sort_by?: string;
  sort_dir?: string;
}): Promise<CaseReviewListResponse> {
  const { data } = await http.get('/admin/cases/review-queue', { params });
  return data;
}

export async function getReviewQueueStats(): Promise<ReviewQueueStats> {
  const { data } = await http.get('/admin/cases/review-queue/stats');
  return data;
}

export async function getCaseDetail(caseId: number): Promise<ComplaintCaseDetail> {
  const { data } = await http.get(`/admin/cases/${caseId}`);
  return data;
}

export async function updateCase(caseId: number, updates: Record<string, unknown>): Promise<{ id: number; updated_fields: string[] }> {
  const { data } = await http.put(`/admin/cases/${caseId}`, updates);
  return data;
}

export async function reviewCases(body: {
  action: string;
  reason?: string;
  case_ids: number[];
  mark_published?: boolean;
}): Promise<ReviewActionResponse> {
  const { data } = await http.post('/admin/cases/review', body);
  return data;
}

export async function dedupCheckCase(caseId: number, autoMark?: boolean): Promise<{
  is_duplicate: boolean;
  method: string;
  duplicates: Array<Record<string, unknown>>;
  candidates: Array<Record<string, unknown>>;
  auto_resolved: boolean;
}> {
  const { data } = await http.post('/admin/cases/dedup-check', { case_id: caseId, auto_mark: autoMark ?? true });
  return data;
}

export async function getPublicCaseList(params: {
  province?: string;
  decision_type?: string;
  search?: string;
  limit?: number;
  offset?: number;
}): Promise<{ total: number; cases: Array<Record<string, unknown>> }> {
  const { data } = await http.get('/admin/cases/public/list', { params });
  return data;
}

export async function getPublicCaseDetail(caseId: number): Promise<Record<string, unknown>> {
  const { data } = await http.get(`/admin/cases/public/${caseId}`);
  return data;
}

// ═══════════════════════════════════════════════════════════════
// 候选规则管理 (Phase 2) — Admin only
// ═══════════════════════════════════════════════════════════════

export interface CandidateRuleListResponse {
  total: number;
  limit: number;
  offset: number;
  candidates: CandidateRuleItem[];
}

export async function getCandidateRules(params: {
  review_status?: string;
  source_type?: string;
  min_confidence?: number;
  risk_level?: string;
  limit?: number;
  offset?: number;
}): Promise<CandidateRuleListResponse> {
  const { data } = await http.get('/admin/candidate-rules', { params });
  return data;
}

export async function getCandidateRuleStats(): Promise<{
  by_status: Record<string, number>;
  pending_total: number;
  by_risk_level: Record<string, number>;
  total: number;
}> {
  const { data } = await http.get('/admin/candidate-rules/stats');
  return data;
}

export async function getCandidateRuleDetail(candidateId: number): Promise<CandidateRuleDetail> {
  const { data } = await http.get(`/admin/candidate-rules/${candidateId}`);
  return data;
}

export async function reviewCandidateRules(body: {
  candidate_ids: number[];
  action: string;
  note?: string;
  promoted_rule_id?: string;
}): Promise<{
  action: string;
  success_count: number;
  error_count: number;
  results: Array<Record<string, unknown>>;
  errors: Array<Record<string, unknown>>;
}> {
  const { data } = await http.post('/admin/candidate-rules/review', body);
  return data;
}
