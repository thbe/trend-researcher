import { ApiError } from './client'

export interface CrawlConfig {
  source_name: string
  enabled: boolean
  top_n: number
  capture_summary: boolean
  verify_ssl: boolean
  feed_url: string | null
  updated_at: string
}

export interface CrawlConfigCreate {
  source_name: string
  enabled?: boolean
  top_n?: number
  capture_summary?: boolean
  verify_ssl?: boolean
  feed_url?: string | null
}

export async function listCrawlConfig(): Promise<CrawlConfig[]> {
  const res = await fetch('/api/crawl-config', {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`)
  return (await res.json()) as CrawlConfig[]
}

export async function createCrawlConfig(data: CrawlConfigCreate): Promise<CrawlConfig> {
  const res = await fetch('/api/crawl-config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`)
  return (await res.json()) as CrawlConfig
}

export async function updateCrawlConfig(
  sourceName: string,
  data: { enabled?: boolean; top_n?: number; capture_summary?: boolean; verify_ssl?: boolean; feed_url?: string | null },
): Promise<CrawlConfig> {
  const res = await fetch(`/api/crawl-config/${sourceName}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`)
  return (await res.json()) as CrawlConfig
}

export async function deleteCrawlConfig(sourceName: string): Promise<void> {
  const res = await fetch(`/api/crawl-config/${sourceName}`, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`)
}
