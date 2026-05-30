// Dashboard summary aggregates topics/assessments for the active department.
//
// Must go through the shared `request()` helper so the X-Active-Department
// header is injected — superadmins are required to specify an explicit
// department on this endpoint (server returns 400 otherwise).
import { request } from './client'

export interface DashboardData {
  total_topics: number
  assessed_topics: number
  opportunities: number
  risks: number
  neutral: number
}

export async function getDashboard(): Promise<DashboardData> {
  return request<DashboardData>('/api/dashboard')
}
