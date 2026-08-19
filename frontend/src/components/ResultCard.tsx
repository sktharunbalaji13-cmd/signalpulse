import type { SearchResultItem } from '../api/client'
import { SourceChip } from './SourceChip'

type ResultCardProps = {
  result: SearchResultItem
}

function formatTime(iso: string | null): string {
  if (iso === null) {
    return 'Not provided by source'
  }
  return new Date(iso).toLocaleString()
}

export function ResultCard({ result }: ResultCardProps) {
  return (
    <article className="result-card">
      <div className="result-card__meta">
        <SourceChip sourceType={result.source_type} />
        <span>{result.source_name}</span>
      </div>
      <h3>
        <a href={result.url} target="_blank" rel="noopener noreferrer">
          {result.title}
        </a>
      </h3>
      {result.description && <p>{result.description}</p>}
      <p className="result-card__times">
        Published: {formatTime(result.published_at)} · Retrieved: {formatTime(result.retrieved_at)}
      </p>
    </article>
  )
}