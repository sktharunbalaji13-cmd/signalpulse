import type { SourceStatus } from '../api/client'

type SourceStatusSummaryProps = {
  sources: SourceStatus[]
}

export function SourceStatusSummary({ sources }: SourceStatusSummaryProps) {
  if (sources.length === 0) {
    return null
  }
  return (
    <ul className="source-signals" aria-label="Source signals">
      {sources.map((source) => {
        const ok = source.status === 'success'
        const count = source.result_count ?? 0
        return (
          <li
            key={source.name}
            className={`srcsig ${ok ? 'srcsig--ok' : 'srcsig--error'}`}
          >
            <div className="srcsig__head">
              <span>
                {ok ? '✓ ' : '⚠ '}
                {source.name}
              </span>
            </div>
            {ok ? (
              <>
                <div className="srcsig__count">
                  {count} {count === 1 ? 'result' : 'results'}
                </div>
                {source.latency_ms != null && (
                  <div className="srcsig__latency">{source.latency_ms} ms</div>
                )}
              </>
            ) : (
              <div className="srcsig__count">unavailable</div>
            )}
          </li>
        )
      })}
    </ul>
  )
}