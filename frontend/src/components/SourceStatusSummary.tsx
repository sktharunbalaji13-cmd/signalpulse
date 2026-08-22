import type { SourceStatus } from '../api/client'

type SourceStatusSummaryProps = {
  sources: SourceStatus[]
}

function describeSource(source: SourceStatus): string {
  switch (source.status) {
    case 'success': {
      const count = source.result_count ?? 0
      const label = `${count} ${count === 1 ? 'result' : 'results'}`
      return source.latency_ms != null
        ? `${source.name} ✓ ${label} · ${source.latency_ms} ms`
        : `${source.name} ✓ ${label}`
    }
    case 'timeout':
      return `${source.name} timed out`
    case 'rate_limited':
      return `${source.name} rate limited`
    default:
      return `${source.name} unavailable`
  }
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
