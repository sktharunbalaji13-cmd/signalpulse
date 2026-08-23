import type { SearchResultItem } from '../api/client'
import { formatTimestamp } from '../utils/format'
import { SourceChip } from './SourceChip'

type ResultCardProps = {
  result: SearchResultItem
  rank?: number
}

export function ResultCard({ result, rank }: ResultCardProps) {
  return (
    <article className="signal">
      <div className="signal__rank" aria-label={`Signal rank ${rank ?? ''}`}>
        #{rank !== undefined ? String(rank).padStart(2, '0') : ''}
      </div>
      <div className="signal__body">
        <div className="signal__tags">
          <SourceChip sourceType={result.source_type} />
          <span>{result.source_name}</span>
          {result.is_duplicate && <span className="chip chip--duplicate">duplicate</span>}
        </div>
        <h3>
          <a href={result.url} target="_blank" rel="noopener noreferrer">
            {result.title}
          </a>
        </h3>
        {result.author && <p className="signal__byline">By {result.author}</p>}
        {result.description && (
          <p className="signal__description">{result.description}</p>
        )}
        <p className="signal__times">
          Published: {formatTimestamp(result.published_at)} · Retrieved:{' '}
          {formatTimestamp(result.retrieved_at)}
        </p>
      </div>
    </article>
  )
}