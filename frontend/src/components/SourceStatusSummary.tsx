import type { SourceStatus } from '../api/client'

type SourceStatusSummaryProps = {
  sources: SourceStatus[]
}

function describeSource(source: SourceStatus): string {
  switch (source.status) {
    case 'success': {
      const count = source.result_count ?? 0
      const label = `${count} ${count === 1 ? 'result' : 'results'}`
      const latency = source.latency_ms != null ? ` · ${source.latency_ms} ms` : ''
      return `${source.name} · ${label}${latency}`
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
      {sources.map((source) => {
        const ok = source.status === 'success'
        return (
          <li
            key={source.name}
            className={`source-summary__item ${ok ? 'source-summary__item--ok' : 'source-summary__item--error'}`}
          >
            <span>{ok ? '✓ ' : '⚠ '}{describeSource(source)}</span>
          </li>
        )
      })}
    </ul>
  )
}