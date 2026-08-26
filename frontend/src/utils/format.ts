export function formatTimestamp(iso: string | null): string {
  if (iso === null) {
    return 'Not provided by source'
  }
  return new Date(iso).toLocaleString()
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString()
}

/** M23 FE-C: compact relative time ("just now", "5m ago", "2h ago", "3d ago"). */
export function formatRelativeTime(iso: string, now: number = Date.now()): string {
  const timestamp = new Date(iso).getTime()
  if (Number.isNaN(timestamp)) {
    return 'time unknown'
  }
  const seconds = Math.max(0, Math.floor((now - timestamp) / 1000))
  if (seconds < 60) {
    return 'just now'
  }
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) {
    return `${minutes}m ago`
  }
  const hours = Math.floor(minutes / 60)
  if (hours < 24) {
    return `${hours}h ago`
  }
  const days = Math.floor(hours / 24)
  if (days < 7) {
    return `${days}d ago`
  }
  const weeks = Math.floor(days / 7)
  if (weeks < 5) {
    return `${weeks}w ago`
  }
  return formatDate(iso)
}
