import { useEffect, useState } from 'react'

import { api } from './api/client'
import { ResultCard } from './components/ResultCard'
import { SearchBar } from './components/SearchBar'
import { SourceStatusSummary } from './components/SourceStatusSummary'
import { useSearch } from './hooks/useSearch'

function App() {
  const { viewState, query, resultCount, results, sources, error, runSearch } = useSearch()
  const [apiStatus, setApiStatus] = useState('checking…')

  useEffect(() => {
    api
      .getHealth()
      .then((data) => setApiStatus(data.status))
      .catch(() => setApiStatus('unreachable'))
  }, [])

  const searching = viewState === 'searching'

  return (
    <main className="app">
      <header>
        <h1>SignalPulse</h1>
        <p className="subtitle">Real-time multi-source information intelligence.</p>
        <p className="dev-badge">Development preview · Wikipedia source · API {apiStatus}</p>
      </header>

      <SearchBar disabled={searching} onSearch={runSearch} />

      <section aria-live="polite" className="results-section">
        {searching && <p className="status-text">Searching…</p>}

        {viewState === 'failed' && (
          <>
            <p className="status-text status-text--error" role="alert">
              {error}
            </p>
            <SourceStatusSummary sources={sources} />
          </>
        )}

        {viewState === 'partial' && (
          <p className="status-text status-text--warning">
            Some sources were unavailable. Showing available results.
          </p>
        )}

        {(viewState === 'completed' || viewState === 'partial') && (
          <>
            <h2 className="results-heading">
              Results for: &quot;{query}&quot;
            </h2>
            <SourceStatusSummary sources={sources} />
            {results.length === 0 ? (
              <p className="status-text">No results found.</p>
            ) : (
              <>
                <p className="result-count">
                  {resultCount} {resultCount === 1 ? 'result' : 'results'}
                </p>
                <div className="results">
                  {results.map((result, index) => (
                    <ResultCard key={`${result.url}-${index}`} result={result} />
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </section>
    </main>
  )
}

export default App