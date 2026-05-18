// Typed wrappers for assessment API endpoints.
import { request } from './client'

export interface BusinessCase {
  id: string
  topic_id: string
  title: string
  relevance_verdict: string
  relevance_reason: string
  model_used: string
  prompt_version: string
  generated_at: string
}

export interface AssessBatchResponse {
  assessed: number
  relevant: number
  results: Array<{
    relevance_verdict: string
    relevance_reason: string
    topic_id: string
  }>
}

export function listBusinessCases(limit = 50): Promise<BusinessCase[]> {
  return request<BusinessCase[]>(`/api/business-cases?limit=${limit}`)
}

export async function assessBatch(): Promise<AssessBatchResponse> {
  const response = await fetch('/api/assess', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`Assessment failed: ${response.status}`)
  }
  return response.json()
}

export async function assessTopic(topicId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`/api/assess/${encodeURIComponent(topicId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`Assessment failed: ${response.status}`)
  }
  return response.json()
}
