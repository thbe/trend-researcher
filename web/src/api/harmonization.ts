// API client for harmonization endpoints (Phase 10, plan 10-05 T06).

import { request } from './client'

export interface HarmonizationBusinessCase {
  id: string
  department: { id: string; name: string }
  framework: { id: string; key: string; name: string; display_component: string }
  structured_output: Record<string, unknown>
  relevance_verdict: string
  importance_score: number | null
  confidence: number | null
  created_at: string
  model_used: string
}

export interface HarmonizationNetView {
  text: string
  authored_by: { id: string; username: string } | null
  authored_at: string
  updated_at: string
}

export interface HarmonizationResponse {
  topic: {
    id: string
    title: string
    description: string | null
    first_seen_at: string
    last_seen_at: string
  }
  business_cases: HarmonizationBusinessCase[]
  net_view: HarmonizationNetView | null
}

export async function getHarmonization(topicId: string): Promise<HarmonizationResponse> {
  return request<HarmonizationResponse>(`/api/topics/${topicId}/harmonization`)
}

export async function putHarmonization(
  topicId: string,
  netView: string,
): Promise<HarmonizationResponse> {
  return request<HarmonizationResponse>(`/api/topics/${topicId}/harmonization`, {
    method: 'PUT',
    body: { net_view: netView },
  })
}

export async function deleteHarmonization(topicId: string): Promise<void> {
  return request<void>(`/api/topics/${topicId}/harmonization`, {
    method: 'DELETE',
  })
}
