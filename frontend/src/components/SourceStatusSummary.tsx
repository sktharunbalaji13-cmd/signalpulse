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
        const disabled = source.status === 'disabled'
        const count = source.result_count ?? 0
        return (
          <li
            key={source.name}
            className={`srcsig ${ok ? 'srcsig--ok' : disabled ? 'srcsig--disabled' : 'srcsig--error'}`}
          >
            <div className="srcsig__head">
              <span>
                {ok ? '✓ ' : disabled ? '○ ' : '⚠ '}
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
            ) : disabled ? (
              <div className="srcsig__count">disabled</div>
            ) : (
              <div className="srcsig__count">unavailable</div>
            )}
          </li>
        )
      })}
    </ul>
  )
}