import type { LocalHistoryItem } from '../utils/historyStorage'
import { formatDate } from '../utils/format'

type SearchHistoryProps = {
  items: LocalHistoryItem[]
  disabled?: boolean
  /** M23: highlight the history row matching the currently-visible query. */
  activeQuery?: string
  onSelect: (item: LocalHistoryItem) => void
}

export function SearchHistory({ items, disabled = false, activeQuery, onSelect }: SearchHistoryProps) {
  if (items.length === 0) {
    return <p className="history-empty">No searches yet.</p>
  }
  return (
    <ul className="history-list" aria-label="Recent searches">
      {items.map((item) => (
        <li key={item.search_id}>
          <button
            type="button"
            className={`history-item ${item.query === activeQuery ? 'history-item--active' : ''}`}
            disabled={disabled}
            onClick={() => onSelect(item)}
          >
            <span className="history-item__query">{item.query}</span>
            <span className={`history-item__meta history-item__meta--${item.status}`}>
              {item.status} · {item.result_count}{' '}
              {item.result_count === 1 ? 'result' : 'results'} · {formatDate(item.created_at)}
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}