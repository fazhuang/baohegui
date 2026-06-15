/** Admin panel types — re-exported from api.ts */

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
