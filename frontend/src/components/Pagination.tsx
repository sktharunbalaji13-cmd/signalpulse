type PaginationProps = {
  page: number
  totalPages: number
  disabled?: boolean
  onPageChange: (page: number) => void
}

export function Pagination({ page, totalPages, disabled = false, onPageChange }: PaginationProps) {
  if (totalPages <= 1) {
    return null
  }
  return (
    <nav className="pagination" aria-label="Result pages">
      <button
        type="button"
        onClick={() => onPageChange(page - 1)}
        disabled={disabled || page <= 1}
      >
        &larr; Previous
      </button>
      <span className="pagination__status">
        Page {page} of {totalPages}
      </span>
      <button
        type="button"
        onClick={() => onPageChange(page + 1)}
        disabled={disabled || page >= totalPages}
      >
        Next &rarr;
      </button>
    </nav>
  )
}
