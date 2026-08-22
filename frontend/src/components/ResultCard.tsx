import type { SearchResultItem } from '../api/client'
import { formatTimestamp } from '../utils/format'
import { SourceChip } from './SourceChip'

type ResultCardProps = {
  result: SearchResultItem
  rank?: number
}

export function ResultCard({ result, rank }: ResultCardProps) {
  return (
    <article className="result-card">
      <div className="result-card__meta">
        {rank !== undefined && <span className="result-card__rank">#{rank}</span>}
        <SourceChip sourceType={result.source_type} />
        <span>{result.source_name}</span>
        {result.is_duplicate && <span className="chip chip--duplicate">duplicate</span>}
      </div>
      <h3>
        <a href={result.url} target="_blank" rel="noopener noreferrer">
          {result.title}
        </a>
      </h3>
      {result.author && <p className="result-card__byline">By {result.author}</p>}
      {result.description && <p>{result.description}</p>}
      <p className="result-card__times">
        Published: {formatTimestamp(result.published_at)} · Retrieved:{' '}
        {formatTimestamp(result.retrieved_at)}
      </p>
    </article>
  )
}
