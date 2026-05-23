// Typed wrappers over GET /api/topics and GET /api/topics/{id}.
// Field shapes mirror services/api/src/api/schemas.py
// (TopicResponse, TopicsListResponse, TopicSourceResponse,
// TopicDetailResponse).
import { ApiError, request } from './client'

export interface Topic {
  id: string
  title: string
  description: string | null
  first_seen_at: string
  last_seen_at: string
  observation_count: number
  breadth: number
  longevity_seconds: number
  relevance_verdict: string | null
  source_names: string | null
}

export interface TopicSource {
  id: string
  source_name: string
  url: string
  // Plan 04.5-01 (ING-011): decoded publisher URL for google_news CBM
  // redirect tokens. NULL when the source isn't google_news, when the
  // in-process decoder couldn't extract a URL, or for any row created
  // before migration 0004. SPA prefers this over `url` for clickability.
  resolved_url: string | null
  native_rank: number | null
  observed_at: string
}

export interface TopicDetail extends Topic {
  topic_metadata: Record<string, unknown>
  sources: TopicSource[]
}

export interface TopicsListResponse {
  topics: Topic[]
  total: number
  limit: number
  offset: number
  sort: string
}

export function listTopics(
  sort: string = '-last_seen_at',
  limit: number = 20,
  offset: number = 0,
): Promise<TopicsListResponse> {
  const params = new URLSearchParams({ sort, limit: String(limit), offset: String(offset) })
  return request<TopicsListResponse>(`/api/topics?${params.toString()}`)
}

export function getTopic(id: string): Promise<TopicDetail> {
  return request<TopicDetail>(`/api/topics/${encodeURIComponent(id)}`)
}

export interface TopicCleanupRequest {
  source_name?: string | null
  older_than_days?: number | null
}

export interface TopicCleanupResponse {
  topic_sources_deleted: number
  topics_deleted: number
  source_name: string | null
  older_than_days: number | null
}

export async function cleanupTopics(
  body: TopicCleanupRequest,
): Promise<TopicCleanupResponse> {
  const res = await fetch('/api/topics/cleanup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const j = await res.json()
      if (j && typeof j.detail === 'string') detail = j.detail
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as TopicCleanupResponse
}

export async function cleanupOrphanTopics(): Promise<TopicCleanupResponse> {
  const res = await fetch('/api/topics/cleanup-orphans', {
    method: 'POST',
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const j = await res.json()
      if (j && typeof j.detail === 'string') detail = j.detail
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as TopicCleanupResponse
}
