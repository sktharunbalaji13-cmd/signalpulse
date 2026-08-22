import { useEffect, useState } from 'react'

import { api } from './api/client'
import { FilterBar } from './components/FilterBar'
import { Pagination } from './components/Pagination'
import { ResultCard } from './components/ResultCard'
import { SearchBar } from './components/SearchBar'
import { SearchHistory } from './components/SearchHistory'
import { SourceStatusSummary } from './components/SourceStatusSummary'
import { StatusBanner } from './components/StatusBanner'
import { useSearch } from './hooks/useSearch'

const EXAMPLE_QUERIES = ['artificial intelligence', 'quantum computing', 'climate policy']
const PER_PAGE = 20

function App() {
  const search = useSearch()
  const [apiStatus, setApiStatus] = useState('checking…')
  const [retryInSeconds, setRetryInSeconds] = useState(0)

  useEffect(() => {
    api
      .getHealth()
      .then((data) => setApiStatus(data.status))
      .catch(() => setApiStatus('unreachable'))
  }, [])

  useEffect(() => {
    const restoreFromUrl = () => {
      const id = new URLSearchParams(window.location.search).get('s')
      if (id) {
        void search.openSearch(id)
      } else {
        search.reset()
      }
    }
    restoreFromUrl()
    window.addEventListener('popstate', restoreFromUrl)
    return () => window.removeEventListener('popstate', restoreFromUrl)
  }, [search.openSearch, search.reset])

  useEffect(() => {
    if (!search.rateLimitRetryAt) {
      setRetryInSeconds(0)
      return
    }
    const tick = () =>
      setRetryInSeconds(Math.max(0, Math.ceil((search.rateLimitRetryAt! - Date.now()) / 1000)))
    tick()
    const timer = window.setInterval(tick, 500)
    return () => window.clearInterval(timer)
  }, [search.rateLimitRetryAt])

  const busy = search.viewState === 'submitting' || search.viewState === 'running'
  const rateLimited = retryInSeconds > 0
  const showResultsArea =
    search.viewState === 'running' ||
    search.viewState === 'completed' ||
    search.viewState === 'partial'

  return (
    <main className="app">
      <header className="hero">
        <h1>SignalPulse</h1>
        <p className="subtitle">
          Real-time multi-source information intelligence — news, reference and social results,
          ranked and de-duplicated in one place.
        </p>
        <p className="api-badge">API {apiStatus}</p>
      </header>

      <SearchBar
        disabled={busy || rateLimited}
        label={busy ? 'Searching…' : 'Search'}
        onSearch={search.runSearch}
      />

      {search.viewState === 'idle' && (
        <section className="examples" aria-label="Example searches">
          <p className="examples__label">Try:</p>
          {EXAMPLE_QUERIES.map((example) => (
            <button
              key={example}
              type="button"
              className="example-chip"
              onClick={() => void search.runSearch(example)}
            >
              {example}
            </button>
          ))}
        </section>
      )}

      {rateLimited && (
        <StatusBanner kind="error">
          Too many searches — please wait {retryInSeconds}s and try again.
        </StatusBanner>
      )}
      {search.viewState === 'error-network' && (
        <>
          <StatusBanner kind="error">{search.error}</StatusBanner>
          {search.searchId && (
            <button type="button" onClick={() => void search.openSearch(search.searchId!)}>
              Retry
            </button>
          )}
        </>
      )}

      {(busy || showResultsArea) && (
        <section aria-live="polite" aria-busy={busy} className="results-section">
          {search.viewState === 'submitting' && <StatusBanner kind="info">Searching…</StatusBanner>}
          {search.viewState === 'running' && !search.error && (
            <StatusBanner kind="info">
              Searching{search.results.length > 0
                ? ` — ${search.total} result${search.total === 1 ? '' : 's'} so far`
                : '…'}
            </StatusBanner>
          )}

          {showResultsArea && (
            <>
              <h2 className="results-heading">Results for: &quot;{search.query}&quot;</h2>
              <SourceStatusSummary sources={search.sources} />
              {search.viewState === 'partial' && (
                <StatusBanner kind="warning">
                  Some sources were unavailable. Showing available results.
                </StatusBanner>
              )}

              <FilterBar filters={search.filters} onChange={search.setFilters} />

              {search.results.length === 0 ? (
                <p className="status-text">
                  {search.page > 1 ? 'No results on this page.' : 'No results found.'}
                </p>
              ) : (
                <>
                  <p className="result-count">
                    {search.total} {search.total === 1 ? 'result' : 'results'}
                    {search.totalPages > 1 ? ` · page ${search.page} of ${search.totalPages}` : ''}
                  </p>
                  <div className="results">
                    {search.results.map((result, index) => (
                      <ResultCard
                        key={`${result.url}-${index}`}
                        result={result}
                        rank={(search.page - 1) * PER_PAGE + index + 1}
                      />
                    ))}
                  </div>
                  <Pagination
                    page={search.page}
                    totalPages={search.totalPages}
                    onPageChange={search.goToPage}
                  />
                </>
              )}
            </>
          )}
        </section>
      )}

      {search.viewState === 'failed' && (
        <section aria-live="polite" className="results-section">
          <StatusBanner kind="error">
            Search failed. Every source was unavailable — please try again shortly.
          </StatusBanner>
          <SourceStatusSummary sources={search.sources} />
        </section>
      )}

      <details className="history">
        <summary>Recent searches</summary>
        <SearchHistory items={search.history} onSelect={(id) => void search.openSearch(id)} />
      </details>
    </main>
  )
}

export default App
