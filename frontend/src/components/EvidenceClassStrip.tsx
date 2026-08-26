import type { SourceStatus } from '../api/client'
import { classifySources, type ClassAggregate } from '../utils/evidence'

type EvidenceClassStripProps = {
  sources: SourceStatus[]
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
 * M23 FE-B: "which evidence classes contributed to this search". Renders one
 * pill per evidence class with its aggregate result count, plus an explicit
 * dormant state when a class's sources are all disabled (e.g. social).
 */
export function EvidenceClassStrip({ sources }: EvidenceClassStripProps) {
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
        {aggregates.map((aggregate) => (
          <li
            key={aggregate.id}
            className={`class-chip class-chip--${aggregate.status}`}
            title={
              aggregate.sources.length > 0
                ? aggregate.sources.join(', ')
                : undefined
            }
          >
            <span className="class-chip__label">{aggregate.label}</span>
            <span className="class-chip__count">{renderState(aggregate)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}