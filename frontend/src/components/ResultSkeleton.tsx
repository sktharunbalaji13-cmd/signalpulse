export function ResultSkeleton() {
  return (
    <div className="skeleton-card" data-testid="result-skeleton" aria-hidden="true">
      <div className="skeleton-line skeleton-line--short" />
      <div className="skeleton-line skeleton-line--title" />
      <div className="skeleton-line" />
      <div className="skeleton-line skeleton-line--short" />
    </div>
  )
}