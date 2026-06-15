/** 包合规前端类型定义 */

// ═══════════════════════════════════════════════════════════════
// 角色体系
// ═══════════════════════════════════════════════════════════════

/** 用户角色 — 5 角色体系 */
export type UserRole = 'super_admin' | 'admin' | 'reviewer' | 'agent' | 'enterprise';

/** 向后兼容：后端暂未迁移到 5 角色时，将旧 role 映射为新角色 */
export function normalizeRole(legacy: string): UserRole {
  switch (legacy) {
    case 'super_admin': return 'super_admin';
    case 'admin': return 'admin';
    case 'reviewer': return 'reviewer';
    case 'agent': return 'agent';
    case 'enterprise': return 'enterprise';
    // 向后兼容映射
    case 'user': return 'agent';
    default: return 'agent';
  }
}

/** 当前登录用户 */
export interface CurrentUser {
  userId: number;
  username: string;
  role: UserRole;
  company: string;
  email: string;
  permissions: string[];
}

/** 权限标识 — 与后端 Permission enum 对齐 */
export type PermissionKey =
  // 文件操作
  | 'file:upload' | 'file:check'
  // 报告操作
  | 'report:view' | 'report:download' | 'report:list_all'
  // 规则管理
  | 'rules:read' | 'rules:write' | 'rules:sync'
  // 管理后台
  | 'admin:users' | 'admin:audit' | 'admin:billing'
  // 系统统计
  | 'stats:dashboard'
  // 知识图谱
  | 'kg:read' | 'kg:seed'
  // 爬虫
  | 'crawler:read' | 'crawler:trigger';

// ═══════════════════════════════════════════════════════════════
// 菜单配置类型
// ═══════════════════════════════════════════════════════════════

/** 菜单分组 */
export interface MenuGroup {
  key: string;
  label: string;
  icon: string;          // @ant-design/icons 组件名
  order: number;          // 排序权重
  visibleTo: UserRole[];  // 哪些角色可见此分组
}

/** 叶子菜单项 */
export interface MenuItem {
  key: string;
  label: string;
  path: string;
  icon: string;
  group: string;          // 所属分组 key
  visibleTo: UserRole[];
  adminOnly?: boolean;    // 标记仅管理员可见（在分组内高亮）
}

// ═══════════════════════════════════════════════════════════════
// 违规项
// ═══════════════════════════════════════════════════════════════

/** 违规项（规则引擎） */
export interface RuleViolation {
  rule_id: string
  rule_type: string
  description: string
  location?: string
  text?: string
  evidence_text?: string
  start_offset?: number
  end_offset?: number
  risk_level: 'high' | 'medium' | 'low'
  suggestion: string
  suggestion_detail?: string
  platform_codes: Array<{ platform: string; code: string; desc?: string }>
  law_ref?: string
  legal_basis?: string
  weight: number
}

/** 违规项（大模型） */
export interface LLMViolation {
  type: string
  section: string
  text: string
  evidence_text?: string
  risk_level: string
  reason: string
  suggestion: string
  law_ref?: string
  legal_basis?: string
  suggestion_detail?: string
  weight: number
  /** 证据链校验（v5 新增） */
  validation_error?: string
  requires_human_review?: boolean
}

/** 合规报告 */
export interface ComplianceReport {
  file_name: string
  check_time: string
  total_score: number
  section_score: number
  keyword_score: number
  forbidden_score: number
  semantic_score: number
  rule_violations: RuleViolation[]
  llm_violations: LLMViolation[]
  total_violations: number
  high_risk_count: number
  medium_risk_count: number
  low_risk_count: number
  llm_model_used: string
  llm_tokens_used: number
  llm_cost_yuan: number
  llm_error: string | null
  dedup_cross_engine: number
  dedup_intra_engine: number
  rule_count: number
  /** M1+M2 升级后新增字段 — report_data JSON 字符串 */
  report_data?: string
}

// ═══════════════════════════════════════════════════════════════
// 上传 / 检查
// ═══════════════════════════════════════════════════════════════

/** 上传响应 */
export interface UploadResult {
  file_id: string
  db_id: number
  filename: string
  page_count: number
  sections: Record<string, string>
  industry?: string[] | null
}

/** 检查结果 */
export interface CheckResult {
  report_id: number
  total_score: number
  total_violations: number
  high_risk_count: number
  medium_risk_count: number
  low_risk_count: number
  section_score: number
  keyword_score: number
  forbidden_score: number
  semantic_score: number
  llm_model_used: string
  llm_tokens_used: number
  llm_cost_yuan: number
  llm_error: string | null
  industries?: string[] | null
  /** 五层流水线字段 */
  traffic_light?: string
  routing_reasoning?: string
  parameter_bias_score?: number
  parameter_bias_findings?: number
  merge_risk_level?: string
  merge_review_status?: string
  merge_requires_human_review?: boolean
  merge_confirmed_count?: number
  merge_high_risk_count?: number
}

/** 报告列表项 */
export interface ReportListItem {
  id: number
  file_id: number
  file_name: string
  total_score: number
  violation_count: number
  created_at: string
}

// ═══════════════════════════════════════════════════════════════
// 进度状态
// ═══════════════════════════════════════════════════════════════

/** 上传进度状态 */
export interface UploadProgress {
  stage: string
  bytes_read?: number
  filename?: string
  file_size?: number
  error?: string
}

/** 检查进度状态 */
export interface CheckProgress {
  stage: string
  file_id?: number
  report_id?: number
  error?: string
}

/** 报告列表响应 */
export interface ReportListResponse {
  items: ReportListItem[]
  total: number
  page: number
  page_size: number
  pages: number
}

// ═══════════════════════════════════════════════════════════════
// 管理后台
// ═══════════════════════════════════════════════════════════════

/** 管理后台用户表单 */
export interface CreateUserRequest {
  username: string
  password: string
  role?: string
  company?: string
  email?: string
}

/** 管理后台用户更新表单 */
export interface UpdateUserRequest {
  password?: string
  role?: string
  company?: string
  email?: string
  is_active?: boolean
}

/** 计费告警 */
export interface BillingAlert {
  type: string
  message: string
  severity: 'critical' | 'warning' | 'info'
}

/** 计费状态 */
export interface BillingStatus {
  current_period: string
  tokens: { used: number; limit: number; pct: number }
  cost: { used_yuan: number; limit_yuan: number; pct: number }
  calls: { total: number; success_rate: number }
  alerts: BillingAlert[]
}

// ═══════════════════════════════════════════════════════════════
// 规则管理
// ═══════════════════════════════════════════════════════════════

/** 平台规则 */
export interface PlatformRule {
  rule_id: string
  platform: string
  platform_code: string
  rule_type: string
  target: string
  mandatory: boolean
  description: string
  version: string
  effective_date: string
  enabled: boolean
  category: string
}

/** 规则列表响应 */
export interface RuleListResponse {
  total: number
  rules: PlatformRule[]
  platforms: string[]
}

/** 同步结果 */
export interface SyncResultData {
  new_rules: number
  updated_rules: number
  disabled_rules: number
  errors: string[]
}

/** 同步记录 */
export interface SyncHistoryItem {
  id: string
  platform: string
  status: string
  started_at: string
  finished_at: string
  new_rules: number
  updated_rules: number
  errors: string[]
  retry_count: number
  version: string
}

/** 同步状态 */
export interface SyncStatus {
  running: boolean
  actively_syncing: boolean
  total_syncs: number
  last_sync: { platform: string; status: string; time: string } | null
  sync_interval_hours: number
  total_rules?: number
  enabled_rules?: number
  rule_engine_loaded?: number
  platforms?: string[]
  available_platforms?: string[]
}

/** 规则引擎状态 */
export interface EngineStatus {
  total: number
  by_type: Record<string, number>
}

// ═══════════════════════════════════════════════════════════════
// 统计看板
// ═══════════════════════════════════════════════════════════════

/** 管理看板统计数据 */
export interface DashboardStats {
  rules: {
    total: number
    by_type: Record<string, number>
    chapter_required: number
    keyword_required: number
    forbidden: number
    format_required: number
  }
  llm: {
    total_calls: number
    total_tokens: number
    total_cost: number
    success_rate: number
    avg_tokens_per_call: number
    calls_by_model: Record<string, number>
    recent_calls: Array<{
      model: string
      tokens: number
      duration: number
      success: boolean
      timestamp: string
    }>
  }
  risk_distribution: {
    high: number
    medium: number
    low: number
  }
  industries: string[]
}
