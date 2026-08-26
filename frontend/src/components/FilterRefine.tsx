import { useState } from 'react'

import type { SourceStatus } from '../api/client'
import type { Filters } from '../hooks/useSearch'
import { FilterBar } from './FilterBar'

type FilterRefineProps = {
  filters: Filters
  sources?: SourceStatus[]
  disabled?: boolean
  onChange: (next: Partial<Filters>) => void
}

function summarize(filters: Filters): string {
  const parts: string[] = []
  if (filters.sourceTypes.length === 0) {
    parts.push('All sources')
  } else {
    parts.push(filters.sourceTypes.join(', '))
  }
  parts.push(filters.time === 'all' ? 'All time' : filters.time)
  if (filters.duplicates === 'canonical') {
    parts.push('canonical only')
  } else {
    parts.push('All duplicates')
  }
  if (filters.language !== '') {
    parts.push(filters.language)
  }
  return parts.join(' · ')
}

function countActive(filters: Filters): number {
  return (
    filters.sourceTypes.length +
    (filters.time !== 'all' ? 1 : 0) +
    (filters.duplicates === 'canonical' ? 1 : 0) +
    (filters.language !== '' ? 1 : 0)
  )
}

/**
 * M23.1: the single "Filter & refine" collapsible, used pre- and post-search.
 *
 * Reuses the existing FilterBar controls — no second implementation. The body
 * is `hidden` while collapsed (accessible + testable) and the shared filters
 * state stays in the caller, so selected filters persist across collapses.
 * On desktop (>=1081px) this in-flow instance is hidden by CSS; the rail's
 * persistent filter panel is the desktop surface. Mobile (<1081px) hides the
 * rail panel instead, so exactly one filter surface is live per breakpoint.
 */
export function FilterRefine({ filters, sources, disabled, onChange }: FilterRefineProps) {
  const [open, setOpen] = useState(false)
  const active = countActive(filters)
  return (
    <section
      className={`filter-refine ${open ? 'filter-refine--open' : ''}`}
      aria-label="Filter & refine"
    >
      <button
        type="button"
        className="filter-refine__head"
        aria-expanded={open}
        aria-controls="filter-refine-body"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="filter-refine__title">Filter & refine</span>
        <span className="filter-refine__summary">{summarize(filters)}</span>
        {active > 0 && <span className="filter-refine__badge">{active} active</span>}
        <span className="filter-refine__toggle" aria-hidden="true">
          {open ? '−' : '+'}
        </span>
      </button>
      <div id="filter-refine-body" className="filter-refine__body" hidden={!open}>
        <FilterBar filters={filters} sources={sources} disabled={disabled} onChange={onChange} />
      </div>
    </section>
  )
}