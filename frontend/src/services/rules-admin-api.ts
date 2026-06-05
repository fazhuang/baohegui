// ── Rules Admin API ───────────────────────────────────────────
// Typed API functions for the rules admin dashboard frontend.

const API_BASE = '/api/rules'

// ── Types ────────────────────────────────────────────────────

export interface RuleStat {
  rule_id: string
  hit_count: number
  total_reports: number
  hit_rate: number
  description: string
}

export interface RulesStats {
  total_rules: number
  by_type: Record<string, number>
  by_category: Record<string, number>
  by_risk: Record<string, number>
  last_reload: string | null
}

export interface RuleVersion {
  version: string
  description: string
  rule_count: number
  created_at: string
  filename: string
}

export interface RuleRecord {
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

export interface RuleListResponse {
  total: number
  rules: RuleRecord[]
}

// ── API Functions ────────────────────────────────────────────

export async function fetchRulesStats(): Promise<RulesStats> {
  const resp = await fetch(`${API_BASE}/stats`, { credentials: 'include' })
  if (!resp.ok) throw new Error(`Failed to fetch stats: ${resp.status}`)
  return resp.json()
}

export async function fetchEffectiveness(): Promise<{ rules: RuleStat[]; total_reports: number }> {
  const resp = await fetch(`${API_BASE}/effectiveness`, { credentials: 'include' })
  if (!resp.ok) throw new Error(`Failed to fetch effectiveness: ${resp.status}`)
  return resp.json()
}

export async function fetchVersions(): Promise<{ versions: RuleVersion[] }> {
  const resp = await fetch(`${API_BASE}/versions`, { credentials: 'include' })
  if (!resp.ok) throw new Error(`Failed to fetch versions: ${resp.status}`)
  return resp.json()
}

export async function rollbackVersion(filename: string): Promise<{ status: string; message: string }> {
  const resp = await fetch(`${API_BASE}/versions/rollback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ filename }),
  })
  if (!resp.ok) throw new Error(`Failed to rollback: ${resp.status}`)
  return resp.json()
}

export async function batchToggleRules(ruleIds: string[], enabled: boolean): Promise<{ status: string; toggled: number }> {
  const resp = await fetch(`${API_BASE}/batch/toggle`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ rule_ids: ruleIds, enabled }),
  })
  if (!resp.ok) throw new Error(`Failed to toggle rules: ${resp.status}`)
  return resp.json()
}

export async function fetchAllRules(search?: string): Promise<RuleListResponse> {
  const params = new URLSearchParams()
  if (search) params.set('search', search)
  const qs = params.toString()
  const url = `${API_BASE}/list${qs ? `?${qs}` : ''}`
  const resp = await fetch(url, { credentials: 'include' })
  if (!resp.ok) throw new Error(`Failed to fetch rules: ${resp.status}`)
  return resp.json()
}
