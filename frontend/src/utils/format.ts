export function formatTimestamp(iso: string | null): string {
  if (iso === null) {
    return 'Not provided by source'
  }
  return new Date(iso).toLocaleString()
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString()
}
