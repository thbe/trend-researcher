import { ApiError } from './client'

export interface CrawlConfig {
  source_name: string
  enabled: boolean
  top_n: number
  capture_summary: boolean
  feed_url: string | null
  updated_at: string
}

export async function listCrawlConfig(): Promise<CrawlConfig[]> {
  const res = await fetch('/api/crawl-config', {
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`)
  return (await res.json()) as CrawlConfig[]
}

export async function updateCrawlConfig(
  sourceName: string,
  data: { enabled?: boolean; top_n?: number },
): Promise<CrawlConfig> {
  const res = await fetch(`/api/crawl-config/${sourceName}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`)
  return (await res.json()) as CrawlConfig
}
