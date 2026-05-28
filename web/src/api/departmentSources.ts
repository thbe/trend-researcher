// Per-department source subscriptions (Phase 10 MT-006).
//
// Backed by services/api/src/api/routes/department_sources.py. The active
// department is resolved server-side from the X-Active-Department header
// injected by client.ts, so callers never specify a dept id here.

import { request } from './client'

export interface DepartmentSource {
  source_name: string
  enabled: boolean
  top_n: number
  capture_summary: boolean
  verify_ssl: boolean
  feed_url: string | null
}

export interface DepartmentSourcesListResponse {
  sources: DepartmentSource[]
  total: number
}

export function listDepartmentSources(): Promise<DepartmentSourcesListResponse> {
  return request<DepartmentSourcesListResponse>('/api/department-sources')
}

export function updateDepartmentSource(
  sourceName: string,
  enabled: boolean,
): Promise<DepartmentSource> {
  return request<DepartmentSource>(
    `/api/department-sources/${encodeURIComponent(sourceName)}`,
    { method: 'PUT', body: { enabled } },
  )
}
