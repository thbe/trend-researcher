// Source tech-config CRUD.
//
// Multi-tenant ownership (plan: source ownership phase):
//   * Each row has an owner `department_id`. The API filters GET by the
//     active department for non-superadmin callers. Superadmin sees all
//     rows but must always pass a department_id on create and is the
//     only role allowed to reassign ownership via PUT.
//   * X-Active-Department is injected by the shared `request()` helper
//     in ./client.ts, so callers never specify it manually.

import { request } from './client'

export interface CrawlConfig {
  source_name: string
  enabled: boolean
  top_n: number
  capture_summary: boolean
  verify_ssl: boolean
  feed_url: string | null
  department_id: string
  department_name: string
  updated_at: string
}

export interface CrawlConfigCreate {
  source_name: string
  enabled?: boolean
  top_n?: number
  capture_summary?: boolean
  verify_ssl?: boolean
  feed_url?: string | null
  /** Required for superadmin; ignored / forced to active dept for others. */
  department_id?: string
}

export interface CrawlConfigUpdate {
  enabled?: boolean
  top_n?: number
  capture_summary?: boolean
  verify_ssl?: boolean
  feed_url?: string | null
  /** Superadmin-only: reassign ownership to another department. */
  department_id?: string
}

export function listCrawlConfig(): Promise<CrawlConfig[]> {
  return request<CrawlConfig[]>('/api/crawl-config')
}

export function createCrawlConfig(data: CrawlConfigCreate): Promise<CrawlConfig> {
  return request<CrawlConfig>('/api/crawl-config', { method: 'POST', body: data })
}

export function updateCrawlConfig(
  sourceName: string,
  data: CrawlConfigUpdate,
): Promise<CrawlConfig> {
  return request<CrawlConfig>(`/api/crawl-config/${encodeURIComponent(sourceName)}`, {
    method: 'PUT',
    body: data,
  })
}

export function deleteCrawlConfig(sourceName: string): Promise<void> {
  return request<void>(`/api/crawl-config/${encodeURIComponent(sourceName)}`, {
    method: 'DELETE',
  })
}
