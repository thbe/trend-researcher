// Same-origin fetch helper. CONTEXT G8: NO base URL, NO env var
// (no VITE_API_BASE_URL). All requests use relative /api/* paths
// which the Vite dev-proxy forwards to :8000 and which FastAPI
// serves directly in prod (CONTEXT G2).

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function request<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = await response.json()
      if (body && typeof body.detail === 'string') {
        detail = body.detail
      }
    } catch {
      // fall through with default detail
    }
    throw new ApiError(response.status, detail)
  }

  return (await response.json()) as T
}
