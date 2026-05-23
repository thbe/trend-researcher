export interface DashboardData {
  total_topics: number
  assessed_topics: number
  opportunities: number
  risks: number
  neutral: number
}

export async function getDashboard(): Promise<DashboardData> {
  const res = await fetch('/api/dashboard')
  if (!res.ok) throw new Error(`Failed to load dashboard: ${res.status}`)
  return res.json()
}
