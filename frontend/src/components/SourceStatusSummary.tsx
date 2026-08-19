import type { SourceStatus } from '../api/client'

type SourceStatusSummaryProps = {
  sources: SourceStatus[]
}

function describeSource(source: SourceStatus): string {
  if (source.status === 'success') {
    return `${source.name} ✓ ${source.result_count} ${source.result_count === 1 ? 'result' : 'results'}`
  }
  return `${source.name} unavailable`
}

export function SourceStatusSummary({ sources }: SourceStatusSummaryProps) {
  if (sources.length === 0) {
    return null
  }
  return (
    <ul className="source-summary" aria-label="Source status">
      {sources.map((source) => (
        <li
          key={source.name}
          className={`source-summary__item ${
            source.status === 'success' ? 'source-summary__item--ok' : 'source-summary__item--error'
          }`}
        >
          {describeSource(source)}
        </li>
      ))}
    </ul>
  )
}