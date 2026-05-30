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

export function assessBatch(frameworkId?: string | null): Promise<AssessJobResponse> {
  // Phase 10 T06: forward-compatible framework_id. Backend may not yet
  // accept this field; unknown body keys are tolerated server-side.
  // Must go through `request()` so X-Active-Department is injected — without
  // it superadmin's POST 400s with "Active department required".
  return request<AssessJobResponse>('/api/assess', {
    method: 'POST',
    body: frameworkId ? { framework_id: frameworkId } : {},
  })
}

export function getJob(jobId: string): Promise<AssessJob> {
  return request<AssessJob>(`/api/assess/jobs/${encodeURIComponent(jobId)}`)
}

export function listJobs(limit = 10): Promise<AssessJob[]> {
  return request<AssessJob[]>(`/api/assess/jobs?limit=${limit}`)
}

export function assessTopic(
  topicId: string,
  frameworkId?: string | null,
): Promise<Record<string, unknown>> {
  // Phase 10 T06: forward-compatible framework_id (see assessBatch).
  // Goes through `request()` to inject X-Active-Department (required for
  // superadmin who has no implicit dept).
  return request<Record<string, unknown>>(
    `/api/assess/${encodeURIComponent(topicId)}`,
    {
      method: 'POST',
      body: frameworkId ? { framework_id: frameworkId } : {},
    },
  )
}
