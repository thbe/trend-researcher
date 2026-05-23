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

export interface OllamaModel {
  name: string
  size: number | null
  modified_at: string | null
}

export async function getAIConfig(): Promise<AIConfig> {
  const res = await fetch('/api/ai-config')
  if (!res.ok) throw new Error(`Failed to load AI config: ${res.status}`)
  return res.json()
}

export async function updateAIConfig(
  data: {
    base_url?: string
    model?: string
    api_token?: string | null
    business_context?: string | null
    opportunity_criteria?: string | null
    risk_criteria?: string | null
    thinking_effort?: string
    request_timeout_seconds?: number
  },
): Promise<AIConfig> {
  const res = await fetch('/api/ai-config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`Failed to update AI config: ${res.status}`)
  return res.json()
}

export async function listAvailableModels(): Promise<OllamaModel[]> {
  const res = await fetch('/api/ai-config/models')
  if (!res.ok) throw new Error(`Failed to fetch models: ${res.status}`)
  return res.json()
}
