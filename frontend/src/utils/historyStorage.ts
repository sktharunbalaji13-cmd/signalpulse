const STORAGE_KEY = 'signalpulse:history'
const MAX_ITEMS = 20

export type LocalHistoryItem = {
  search_id: string
  query: string
  created_at: string
  status: string
  result_count: number
}
/** M19.1 (ADR 0015): "history" means searches previously initiated from this
 * browser. Query labels live in localStorage; the server never publishes a
 * global query list. Corrupt/missing storage degrades to an empty list. */
export function loadLocalHistory(): LocalHistoryItem[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (item): item is LocalHistoryItem =>
        typeof item === 'object' &&
        item !== null &&
        typeof (item as LocalHistoryItem).search_id === 'string' &&
        typeof (item as LocalHistoryItem).query === 'string',
    )
  } catch {
    return []
  }
}

function save(items: LocalHistoryItem[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_ITEMS)))
  } catch {
    // Storage unavailable (quota/private mode) - history is best-effort.
  }
}

export function addLocalHistory(item: Omit<LocalHistoryItem, 'status' | 'result_count'>): LocalHistoryItem[] {
  const items = loadLocalHistory().filter((i) => i.search_id !== item.search_id)
  const entry: LocalHistoryItem = { ...item, status: 'running', result_count: 0 }
  const next = [entry, ...items].slice(0, MAX_ITEMS)
  save(next)
  return next
}

export function updateLocalHistory(
  searchId: string,
  patch: Pick<LocalHistoryItem, 'status' | 'result_count'>,
): LocalHistoryItem[] {
  const items = loadLocalHistory().map((i) =>
    i.search_id === searchId ? { ...i, ...patch } : i,
  )
  save(items)
  return items
}