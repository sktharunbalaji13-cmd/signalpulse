import type { SourceStatus } from '../api/client'
import { classifySources, type ClassAggregate } from '../utils/evidence'

type EvidenceClassStripProps = {
  sources: SourceStatus[]
  /** M23: evidence-class ids currently selected as a filter lens. */
  selected?: string[]
  onToggleClass?: (classId: string) => void
}

function renderState(aggregate: ClassAggregate): string {
  if (aggregate.status === 'active') {
    return ` · ${aggregate.count}`
  }
  if (aggregate.status === 'dormant') {
    return ' · dormant'
  }
  if (aggregate.status === 'unavailable') {
    return ' · unavailable'
  }
  return ''
}

/**
 * M23 FE-B + final UX pass: "which evidence classes contributed to this
 * search", rendered as one pill per class. Active/unavailable pills are
 * interactive lenses (tap to filter results by that class via the existing
 * source_type filter); dormant pills stay informational.
 */
export function EvidenceClassStrip({ sources, selected = [], onToggleClass }: EvidenceClassStripProps) {
  if (sources.length === 0) {
    return null
  }
  const aggregates = classifySources(sources).filter(
    (aggregate) => aggregate.status !== 'absent',
  )
  if (aggregates.length === 0) {
    return null
  }
  return (
    <section className="class-strip" aria-label="Evidence classes">
      <p className="eyebrow">Evidence Classes</p>
      <ul className="class-strip__list">
        {aggregates.map((aggregate) => {
          const isLens =
            aggregate.status !== 'dormant' && typeof onToggleClass === 'function'
          const isSelected = selected.includes(aggregate.id)
          return (
            <li
              key={aggregate.id}
              title={aggregate.sources.length > 0 ? aggregate.sources.join(', ') : undefined}
            >
              {isLens ? (
                <button
                  type="button"
                  className={`class-chip class-chip--lens class-chip--${aggregate.status}${
                    isSelected ? ' class-chip--selected' : ''
                  }`}
                  aria-pressed={isSelected}
                  onClick={() => onToggleClass(aggregate.id)}
                >
                  <span className="class-chip__label">{aggregate.label}</span>
                  <span className="class-chip__count">{renderState(aggregate)}</span>
                </button>
              ) : (
                <span className={`class-chip class-chip--${aggregate.status}`}>
                  <span className="class-chip__label">{aggregate.label}</span>
                  <span className="class-chip__count">{renderState(aggregate)}</span>
                </span>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}