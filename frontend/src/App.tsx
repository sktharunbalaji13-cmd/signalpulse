import { useEffect, useState } from 'react'

import { api } from './api/client'
import { AdminDashboard } from './components/AdminDashboard'
import { EmptyState } from './components/EmptyState'
import { EvidenceClassStrip } from './components/EvidenceClassStrip'
import { FilterBar } from './components/FilterBar'
import { Footer } from './components/Footer'
import { Pagination } from './components/Pagination'
import { ResultCard } from './components/ResultCard'
import { ResultSkeleton } from './components/ResultSkeleton'
import { SearchBar } from './components/SearchBar'
import { SearchHistory } from './components/SearchHistory'
import { SourceStatusSummary } from './components/SourceStatusSummary'
import { useSearch, type Filters } from './hooks/useSearch'
import { activeClassCount, impactedClasses } from './utils/evidence'

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
  // M20.1: hash-based admin workspace route (no router dependency), mirroring
  // the existing ?s= deep-link convention.
  const [isAdmin, setIsAdmin] = useState(() => window.location.hash === '#/admin')
  // M23 final pass: search input stays in sync with topic clicks; mobile
  // filters are collapsed behind a "Filter & Refine" toggle by default.
  const [searchInput, setSearchInput] = useState('')
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false)

  useEffect(() => {
    const onHashChange = () => setIsAdmin(window.location.hash === '#/admin')
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

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
  const activeClasses = activeClassCount(search.sources)
  const partialCoverage = search.sources.some(
    (s) => s.status !== 'success' && s.status !== 'disabled',
  )
  const activeFilterCount =
    search.filters.sourceTypes.length +
    (search.filters.time !== 'all' ? 1 : 0) +
    (search.filters.duplicates === 'canonical' ? 1 : 0) +
    (search.filters.language !== '' ? 1 : 0)

  function handleTopicClick(query: string) {
    setSearchInput(query)
    void search.runSearch(query)
  }

  function removeFilter(partial: Partial<Filters>) {
    search.setFilters(partial)
  }

  function handleToggleClass(classId: string) {
    const next = search.filters.sourceTypes.includes(classId)
      ? search.filters.sourceTypes.filter((t) => t !== classId)
      : [...search.filters.sourceTypes, classId]
    search.setFilters({ sourceTypes: next })
  }

  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="topbar">
        <span className="topbar__brand">SIGNALPULSE</span>
        <span className="topbar__right">
          {!isAdmin && (
            <a className="admin-link" href="#/admin">
              Admin
            </a>
          )}
          <span className="status-pill" role="status">
            <span
              className={`status-dot ${engineOnline ? 'status-dot--pulse' : 'status-dot--offline'}`}
              aria-hidden="true"
            />
            {engineOnline ? 'Engine online' : 'Engine offline'}
          </span>
        </span>
      </header>

      {isAdmin ? (
        <main className="app">
          <div className="workspace-header">
            <AdminDashboard />
          </div>
        </main>
      ) : (
      <main className="app" id="main-content" tabIndex={-1}>
        <section className="workspace-header" aria-label="Intelligence workspace">
          <p className="eyebrow">Intelligence Workspace</p>
          <h1>Track a topic across independent sources.</h1>
          <p className="lede">
            One search fans out across evidence classes — news, research, code, Q&A,
            reference and video — and returns ranked, attributed signals. Search once,
            compare evidence across sources.
          </p>

          <div className="search-shell">
            <SearchBar
              disabled={busy || rateLimited}
              label={busy ? 'Searching…' : 'Search'}
              value={searchInput}
              onValueChange={setSearchInput}
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
                    onClick={() => handleTopicClick(example)}
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
                            {activeSources} SOURCE{activeSources === 1 ? '' : 'S'}
                          </span>
                        )}
                        {activeClasses > 0 && (
                          <span className="results-readout__meta">
                            {activeClasses} CLASS{activeClasses === 1 ? '' : 'ES'}
                          </span>
                        )}
                      </div>
                      {activeSources > 0 && activeClasses > 0 && (
                        <p className="results-readout__note">
                          Different sources can contribute to the same evidence class.
                        </p>
                      )}
                    </div>

                    <EvidenceClassStrip
                      sources={search.sources}
                      selected={search.filters.sourceTypes}
                      onToggleClass={handleToggleClass}
                    />

                    <button
                      type="button"
                      className="filter-toggle"
                      aria-expanded={mobileFiltersOpen}
                      onClick={() => setMobileFiltersOpen((open) => !open)}
                    >
                      {mobileFiltersOpen ? 'Hide filters' : 'Filter & refine'}
                      {filtersActive && !mobileFiltersOpen && activeFilterCount > 0 && (
                        <span className="filter-toggle__badge">{activeFilterCount}</span>
                      )}
                    </button>

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
                            .filter((s) => s.status !== 'success' && s.status !== 'disabled')
                            .map((s) => s.name)
                            .join(', ')}{' '}
                          {search.sources.filter((s) => s.status !== 'success' && s.status !== 'disabled').length === 1
                            ? 'is'
                            : 'are'}{' '}
                          currently unavailable. Results from available sources are shown below.
                        </p>
                        {impactedClasses(search.sources).length > 0 && (
                          <p className="notice__detail">
                            Missing evidence classes:{' '}
                            {impactedClasses(search.sources)
                              .map((aggregate) => aggregate.label)
                              .join(', ')}
                            .
                          </p>
                        )}
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

            <aside className={`rail ${mobileFiltersOpen ? '' : 'rail--collapsed'}`}>
              <div className="panel">
                <p className="eyebrow">Filters</p>
                <FilterBar
                  filters={search.filters}
                  sources={search.sources}
                  onChange={search.setFilters}
                />
              </div>

              <div className="panel history-panel">
                <details className="history" open={search.history.length > 0}>
                  <summary>
                    <p className="eyebrow">Recent Queries</p>
                  </summary>
                  <SearchHistory
                    items={search.history}
                    activeQuery={search.query}
                    onSelect={(item) => handleTopicClick(item.query)}
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
                <FilterBar
                  filters={search.filters}
                  sources={search.sources}
                  onChange={search.setFilters}
                />
              </div>
              <div className="panel history-panel">
                <details className="history" open={search.history.length > 0}>
                  <summary>
                    <p className="eyebrow">Recent Queries</p>
                  </summary>
                  <SearchHistory
                    items={search.history}
                    activeQuery={search.query}
                    onSelect={(item) => handleTopicClick(item.query)}
                  />
                </details>
              </div>
            </div>
          </aside>
        )}
      </main>
      )}
      <Footer />
    </>
  )
}

export default App