type EmptyStateProps = {
  message: string
  eyebrow?: string
  actionLabel?: string
  onAction?: () => void
}

export function EmptyState({ message, eyebrow, actionLabel, onAction }: EmptyStateProps) {
  return (
    <div className="empty-state">
      {eyebrow && <p className="eyebrow">{eyebrow}</p>}
      <span className="empty-state__icon" aria-hidden="true">
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="M21 21l-4.35-4.35" />
        </svg>
      </span>
      <p className="empty-state__message">{message}</p>
      {actionLabel && onAction && (
        <button type="button" className="empty-state__action" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  )
}