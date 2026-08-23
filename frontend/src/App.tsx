import { useEffect, useState } from 'react'

import { api } from './api/client'
import { EmptyState } from './components/EmptyState'
import { FilterBar } from './components/FilterBar'
import { Pagination } from './components/Pagination'
import { ResultCard } from './components/ResultCard'
import { ResultSkeleton } from './components/ResultSkeleton'
import { SearchBar } from './components/SearchBar'
import { SearchHistory } from './components/SearchHistory'
import { SourceStatusSummary } from './components/SourceStatusSummary'
import { useSearch, type Filters } from './hooks/useSearch'

const EXAMPLE_QUERIES = ['artificial intelligence', 'quantum computing', 'climate policy']
const PER_PAGE = 20
const DEFAULT_FILTERS: Filters = {
  sourceTypes: [],
  time: 'all',
  duplicates: 'all',
  language: '',
}

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
  const filtersActive =
    search.filters.sourceTypes.length > 0 ||
    search.filters.time !== 'all' ||
    search.filters.duplicates === 'canonical' ||
    search.filters.language !== ''
  const engineOnline = apiStatus === 'ok'
  const activeSources = search.sources.filter((s) => s.status === 'success').length
  const partialCoverage = search.sources.some((s) => s.status !== 'success')

  function removeFilter(partial: Partial<Filters>) {
    search.setFilters(partial)
  }

  return (
    <>
      <header className="topbar">
        <span className="topbar__brand">SIGNALPULSE</span>
        <span className="status-pill" role="status">
          <span
            className={`status-dot ${engineOnline ? 'status-dot--pulse' : 'status-dot--offline'}`}
            aria-hidden="true"
          />
          {engineOnline ? 'Engine online' : 'Engine offline'}
        </span>
      </header>

      <main className="app">
        <section className="workspace-header" aria-label="Intelligence workspace">
          <p className="eyebrow">Intelligence Workspace</p>
          <h1>Track a topic across independent sources.</h1>
          <p className="lede">
            One query sweeps news, reference and social channels — results are ranked and
            de-duplicated before they reach you.
          </p>

          <div className="search-shell">
            <SearchBar
              disabled={busy || rateLimited}
              label={busy ? 'Searching…' : 'Search'}
              onSearch={search.runSearch}
            />
            {search.viewState === 'idle' && (
              <div className="examples" aria-label="Example searches">
                <p className="examples__label">Try</p>
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
              </div>
            )}
          </div>
        </section>

        {rateLimited && (
          <div className="notice notice--error">
            <p>Too many searches — please wait {retryInSeconds}s and try again.</p>
          </div>
        )}
        {search.viewState === 'error-network' && (
          <>
            <div className="notice notice--error">
              <p>{search.error}</p>
            </div>
            {search.searchId && (
              <button type="button" onClick={() => void search.openSearch(search.searchId!)}>
                Retry
              </button>
            )}
          </>
        )}

        {(busy || showResultsArea) && (
          <div className="workspace workspace-pad">
            <div className="workspace__main">
              <section aria-live="polite" aria-busy={busy}>
                {search.viewState === 'submitting' && (
                  <div className="notice">
                    <p>Searching…</p>
                  </div>
                )}
                {search.viewState === 'running' && !search.error && (
                  <div className="notice">
                    <p>
                      Searching
                      {search.results.length > 0
                        ? ` — ${search.total} result${search.total === 1 ? '' : 's'} so far`
                        : '…'}
                    </p>
                  </div>
                )}
                {search.viewState === 'running' && search.results.length === 0 && (
                  <div className="results" aria-hidden="true">
                    <ResultSkeleton />
                    <ResultSkeleton />
                    <ResultSkeleton />
                  </div>
                )}

                {showResultsArea && (
                  <>
                    <div className="results-header">
                      <h2>
                        Results for: <span className="query">&quot;{search.query}&quot;</span>
                      </h2>
                      <div className="results-readout">
                        <span className="results-readout__signals">{search.total} SIGNALS</span>
                        {activeSources > 0 && (
                          <span className="results-readout__meta">
                            {activeSources} SOURCE{activeSources === 1 ? '' : 'S'} ACTIVE
                          </span>
                        )}
                      </div>
                    </div>

                    <p className="eyebrow">Source Signals</p>
                    <SourceStatusSummary sources={search.sources} />

                    {filtersActive && (
                      <div
                        className="active-filters"
                        role="group"
                        aria-label="Active filters"
                      >
                        <span className="active-filters__label">Active Filters</span>
                        {search.filters.sourceTypes.map((sourceType) => (
                          <span key={sourceType} className="filter-chip">
                            {sourceType}
                            <button
                              type="button"
                              className="filter-chip__x"
                              aria-label={`Remove source type filter ${sourceType}`}
                              onClick={() =>
                                removeFilter({
                                  sourceTypes: search.filters.sourceTypes.filter(
                                    (t) => t !== sourceType,
                                  ),
                                })
                              }
                            >
                              ×
                            </button>
                          </span>
                        ))}
                        {search.filters.time !== 'all' && (
                          <span className="filter-chip">
                            {search.filters.time}
                            <button
                              type="button"
                              className="filter-chip__x"
                              aria-label={`Remove time filter ${search.filters.time}`}
                              onClick={() => removeFilter({ time: 'all' })}
                            >
                              ×
                            </button>
                          </span>
                        )}
                        {search.filters.duplicates === 'canonical' && (
                          <span className="filter-chip">
                            canonical
                            <button
                              type="button"
                              className="filter-chip__x"
                              aria-label="Remove duplicates filter"
                              onClick={() => removeFilter({ duplicates: 'all' })}
                            >
                              ×
                            </button>
                          </span>
                        )}
                        {search.filters.language !== '' && (
                          <span className="filter-chip">
                            lang: {search.filters.language}
                            <button
                              type="button"
                              className="filter-chip__x"
                              aria-label={`Remove language filter ${search.filters.language}`}
                              onClick={() => removeFilter({ language: '' })}
                            >
                              ×
                            </button>
                          </span>
                        )}
                      </div>
                    )}

                    {search.viewState === 'partial' && partialCoverage && (
                      <div className="notice notice--warning">
                        <p className="eyebrow">Partial Source Coverage</p>
                        <p>
                          {search.sources
                            .filter((s) => s.status !== 'success')
                            .map((s) => s.name)
                            .join(', ')}{' '}
                          {search.sources.filter((s) => s.status !== 'success').length === 1
                            ? 'is'
                            : 'are'}{' '}
                          currently unavailable. Results from available sources are shown below.
                        </p>
                      </div>
                    )}

                    {search.results.length === 0 ? (
                      search.page > 1 ? (
                        <EmptyState message="No results on this page." />
                      ) : filtersActive ? (
                        <EmptyState
                          eyebrow="No Matching Signals"
                          message="No results match these filters. Try widening the time window or selecting more source types."
                          actionLabel="Reset filters"
                          onAction={() => search.setFilters(DEFAULT_FILTERS)}
                        />
                      ) : (
                        <EmptyState
                          eyebrow="No Signals Returned"
                          message="No results found."
                        />
                      )
                    ) : (
                      <>
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
            </div>

            <aside className="rail">
              <div className="panel">
                <p className="eyebrow">Filters</p>
                <FilterBar filters={search.filters} onChange={search.setFilters} />
              </div>

              <div className="panel history-panel">
                <details className="history" open={search.history.length > 0}>
                  <summary>
                    <p className="eyebrow">Recent Queries</p>
                  </summary>
                  <SearchHistory
                    items={search.history}
                    onSelect={(id) => void search.openSearch(id)}
                  />
                </details>
              </div>
            </aside>
          </div>
        )}

        {search.viewState === 'failed' && (
          <div className="workspace workspace-pad">
            <div className="workspace__main" aria-live="polite">
              <div className="notice notice--error">
                <p className="eyebrow">Search Failed</p>
                <p>Every source was unavailable — please try again shortly.</p>
              </div>
              <SourceStatusSummary sources={search.sources} />
            </div>
          </div>
        )}

        {!busy && !showResultsArea && search.viewState !== 'failed' && (
          <aside className="workspace workspace-pad">
            <div className="rail" style={{ position: 'static' }}>
              <div className="panel">
                <p className="eyebrow">Filters</p>
                <FilterBar filters={search.filters} onChange={search.setFilters} />
              </div>
              <div className="panel history-panel">
                <details className="history" open={search.history.length > 0}>
                  <summary>
                    <p className="eyebrow">Recent Queries</p>
                  </summary>
                  <SearchHistory
                    items={search.history}
                    onSelect={(id) => void search.openSearch(id)}
                  />
                </details>
              </div>
            </div>
          </aside>
        )}
      </main>
    </>
  )
}

export default App