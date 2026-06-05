/** 包合规前端类型定义 */

/** 违规项（规则引擎） */
export interface RuleViolation {
  rule_id: string
  rule_type: string
  description: string
  location?: string
  text?: string
  risk_level: 'high' | 'medium' | 'low'
  suggestion: string
  platform_codes: Array<{ platform: string; code: string; desc?: string }>
  law_ref?: string
  weight: number
}

/** 违规项（大模型） */
export interface LLMViolation {
  type: string
  section: string
  text: string
  risk_level: string
  reason: string
  suggestion: string
  law_ref?: string
  weight: number
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
}

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
  total_score: number
  violation_count: number
  created_at: string
}

/** ── 管理员后台 ─────────────────────────────────── */

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
  // 来自后端 /rules/sync/status
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

/** ── 统计看板 ─────────────────────────────────── */

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
