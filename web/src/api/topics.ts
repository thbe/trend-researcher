// Typed wrappers over GET /api/topics and GET /api/topics/{id}.
// Field shapes mirror services/api/src/api/schemas.py
// (TopicResponse, TopicsListResponse, TopicSourceResponse,
// TopicDetailResponse).
import { request } from './client'

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
  limit: number
  sort: string
}

export function listTopics(
  sort: string = '-last_seen_at',
  limit: number = 20,
): Promise<TopicsListResponse> {
  const params = new URLSearchParams({ sort, limit: String(limit) })
  return request<TopicsListResponse>(`/api/topics?${params.toString()}`)
}

export function getTopic(id: string): Promise<TopicDetail> {
  return request<TopicDetail>(`/api/topics/${encodeURIComponent(id)}`)
}
