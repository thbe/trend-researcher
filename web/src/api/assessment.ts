// Typed wrappers for assessment API endpoints.
import { request } from './client'

/**
 * Framework reference embedded in a BusinessCase response.
 * Populated once the API surface exposes per-case framework info (Phase 10);
 * may be absent on legacy responses.
 */
export interface BusinessCaseFramework {
  id: string
  key: string
  name: string
  display_component: string
}

export interface BusinessCase {
  id: string
  topic_id: string
  title: string
  relevance_verdict: string
  relevance_reason: string
  model_used: string
  prompt_version: string
  generated_at: string
  // Phase 10 (T04): framework-aware fields. Optional for backwards
  // compatibility with pre-10-03 responses that may omit them.
  framework?: BusinessCaseFramework
  structured_output?: Record<string, unknown>
  importance?: number | null
  confidence?: number | null
  category?: string | null
  investment_band?: string | null
  department_id?: string
}

export interface AssessJobResponse {
  job_id: string
  state: string
  total_topics: number
}

export interface AssessJob {
  id: string
  state: string // pending, running, completed, failed
  total_topics: number
  completed_topics: number
  failed_topics: number
  results: { assessed: number; relevant: number; details: unknown[] } | null
  error: string | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
}

export function listBusinessCases(limit = 50, category?: string): Promise<BusinessCase[]> {
  let url = `/api/business-cases?limit=${limit}`
  if (category) url += `&category=${encodeURIComponent(category)}`
  return request<BusinessCase[]>(url)
}

export async function assessBatch(): Promise<AssessJobResponse> {
  const response = await fetch('/api/assess', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  if (!response.ok) {
    let detail = `Assessment failed: ${response.status}`
    try {
      const body = await response.json()
      if (body?.detail) detail = body.detail
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  return response.json()
}

export function getJob(jobId: string): Promise<AssessJob> {
  return request<AssessJob>(`/api/assess/jobs/${encodeURIComponent(jobId)}`)
}

export function listJobs(limit = 10): Promise<AssessJob[]> {
  return request<AssessJob[]>(`/api/assess/jobs?limit=${limit}`)
}

export async function assessTopic(topicId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`/api/assess/${encodeURIComponent(topicId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  if (!response.ok) {
    let detail = `Assessment failed: ${response.status}`
    try {
      const body = await response.json()
      if (body?.detail) detail = body.detail
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  return response.json()
}
