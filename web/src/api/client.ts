// Same-origin fetch helper with multi-tenant header injection + auth
// interceptors.
//
// CONTEXT G8: NO base URL, NO env var. All requests use relative /api/*
// paths which the Vite dev proxy forwards to :8000 and which FastAPI
// serves directly in prod (CONTEXT G2).
//
// Multi-tenant additions (plan 10-04 T02):
//   * Reads the active department id from the Pinia session store and
//     injects it as `X-Active-Department` on every request. Falls back to
//     localStorage when Pinia hasn't been installed yet (eg. the very
//     first hydrate() probe runs against /api/me before any store action
//     populates state — that one doesn't actually need the header but
//     using the fallback keeps the code path uniform).
//   * Response 401 → wipe session state + redirect to /login. The Login
//     view picks the user back up via session.applyLoginResponse().
//   * Response 409 with body `{detail: "active department mismatch"}` is
//     reserved for a future endpoint that re-validates the header; the
//     current backend returns 400 or 403 in those cases instead. We
//     handle it defensively so future plan-aware behaviour lands cleanly.

import { getActivePinia } from 'pinia'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  /** JSON-serialisable body. Sent with `Content-Type: application/json`. */
  body?: unknown
  /** Extra headers, merged after the defaults so callers can override. */
  headers?: Record<string, string>
  /** Disable the auto X-Active-Department header (rare; eg. /api/login). */
  skipActiveDeptHeader?: boolean
  /** Disable the 401 -> /login redirect (rare; eg. probe calls). */
  skipAuthRedirect?: boolean
}

function readActiveDepartmentId(): string | null {
  // Prefer Pinia state when available (single source of truth).
  const pinia = getActivePinia()
  if (pinia) {
    const sess = pinia.state.value['session'] as
      | { activeDepartmentId?: string | null }
      | undefined
    if (sess?.activeDepartmentId) return sess.activeDepartmentId
  }
  // Fallback to the persisted value so requests before store hydration
  // (eg. initial hydrate()) still carry the header.
  if (typeof localStorage !== 'undefined') {
    return localStorage.getItem('activeDepartment')
  }
  return null
}

function redirectToLogin(): void {
  if (typeof window === 'undefined') return
  // Use a hard navigation to fully reset SPA state — the Login view will
  // (re)populate the session store via applyLoginResponse().
  if (window.location.pathname !== '/login') {
    window.location.assign('/login')
  }
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? 'GET'
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(opts.headers ?? {}),
  }

  if (!opts.skipActiveDeptHeader) {
    const activeDept = readActiveDepartmentId()
    if (activeDept) headers['X-Active-Department'] = activeDept
  }

  let body: BodyInit | undefined
  if (opts.body !== undefined) {
    headers['Content-Type'] = headers['Content-Type'] ?? 'application/json'
    body = JSON.stringify(opts.body)
  }

  const response = await fetch(path, { method, headers, body })

  if (response.status === 401 && !opts.skipAuthRedirect) {
    // Wipe any stale session cache, then bounce. Avoid importing the
    // session store (circular: session -> client -> session) — touch
    // localStorage directly.
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem('session')
      localStorage.removeItem('activeDepartment')
    }
    redirectToLogin()
    throw new ApiError(401, 'Unauthorized')
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const data = await response.json()
      if (data && typeof data.detail === 'string') detail = data.detail
    } catch {
      // fall through with default detail
    }
    throw new ApiError(response.status, detail)
  }

  // 204 No Content is a valid success with no body.
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}
