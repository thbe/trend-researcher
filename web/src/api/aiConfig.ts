// AI configuration API wrapper.
//
// Multi-tenant note (Phase 10 plan 10-04): AI config is PER DEPARTMENT.
// All requests must carry X-Active-Department, which the shared `request`
// helper injects from the Pinia session store.
//
// Empty-state: GET /api/ai-config returns 404 with a hint when no row
// exists for the active department yet. `getAIConfig()` translates that
// into `null` so views can render an "Initialize" CTA instead of an error.

import { request, ApiError } from './client'

export interface AIConfig {
  base_url: string
  model: string
  api_token: string | null
  business_context: string | null
  opportunity_criteria: string | null
  risk_criteria: string | null
  thinking_effort: string
  request_timeout_seconds: number
  updated_at: string
}

export interface AIConfigUpdate {
  base_url?: string
  model?: string
  api_token?: string | null
  business_context?: string | null
  opportunity_criteria?: string | null
  risk_criteria?: string | null
  thinking_effort?: string
  request_timeout_seconds?: number
}

export interface OllamaModel {
  name: string
  size: number | null
  modified_at: string | null
}

/**
 * Fetch AI config for the active department.
 * Returns null when no config row exists yet (backend 404 empty-state).
 */
export async function getAIConfig(): Promise<AIConfig | null> {
  try {
    return await request<AIConfig>('/api/ai-config')
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }
}

export function updateAIConfig(data: AIConfigUpdate): Promise<AIConfig> {
  return request<AIConfig>('/api/ai-config', { method: 'PUT', body: data })
}

export function listAvailableModels(): Promise<OllamaModel[]> {
  return request<OllamaModel[]>('/api/ai-config/models')
}
