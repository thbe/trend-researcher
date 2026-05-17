// Display helpers for the longevity_seconds bigint coming off
// v_topic_stats (CONTEXT G4). Buckets are operator-readable, not
// localized — internal tool, single language (English).

export function formatLongevity(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return '—'
  }
  if (seconds < 60) {
    return '<1m'
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m`
  }
  if (seconds < 86400) {
    return `${Math.floor(seconds / 3600)}h`
  }
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  return hours === 0 ? `${days}d` : `${days}d ${hours}h`
}

export function formatRelative(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) {
    return iso
  }
  const deltaSeconds = Math.max(0, Math.floor((Date.now() - then) / 1000))
  return `${formatLongevity(deltaSeconds)} ago`
}
