import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, api } from '../api/client'
import type {
  SearchHistoryItem,
  SearchResultItem,
  SearchStatusResponse,
  SourceStatus,
} from '../api/client'

const POLL_INTERVAL_MS = 700
const PER_PAGE = 20
const RATE_LIMIT_RETRY_MS = 60_000

export type SearchViewState =
  | 'idle'
  | 'submitting'
  | 'running'
  | 'completed'
  | 'partial'
  | 'failed'
  | 'error-network'
  | 'error-rate-limited'
  | 'error-invalid'

export type Filters = {
  sourceTypes: string[]
  time: '24h' | '7d' | '30d' | 'all'
  duplicates: 'all' | 'canonical'
  language: string
}

export const DEFAULT_FILTERS: Filters = {
  sourceTypes: [],
  time: 'all',
  duplicates: 'all',
  language: '',
}

export type SearchState = {
  viewState: SearchViewState
  searchId: string | null
  query: string
  results: SearchResultItem[]
  total: number
  page: number
  totalPages: number
  sources: SourceStatus[]
  error: string | null
  filters: Filters
  history: SearchHistoryItem[]
  rateLimitRetryAt: number | null
}

const initialState: SearchState = {
  viewState: 'idle',
  searchId: null,
  query: '',
  results: [],
  total: 0,
  page: 1,
  totalPages: 1,
  sources: [],
  error: null,
  filters: { ...DEFAULT_FILTERS },
  history: [],
  rateLimitRetryAt: null,
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

function describeApiError(err: unknown): { viewState: SearchViewState; error: string } {
  if (err instanceof ApiError && err.status === 429) {
    return {
      viewState: 'error-rate-limited',
      error: 'Too many searches — please wait about a minute and try again.',
    }
  }
  if (err instanceof ApiError && err.status === 422) {
    return {
      viewState: 'error-invalid',
      error: 'That request was not valid. Adjust the filters or query and try again.',
    }
  }
  return {
    viewState: 'error-network',
    error:
      'Could not reach SignalPulse. The service may be waking up after idle — please retry shortly.',
  }
}

export function useSearch() {
  const [state, setState] = useState<SearchState>(initialState)
  const runIdRef = useRef(0)
  const searchIdRef = useRef<string | null>(null)
  const viewRef = useRef<SearchViewState>('idle')
  const filtersRef = useRef<Filters>({ ...DEFAULT_FILTERS })
  const pageRef = useRef(1)
  const seenCountRef = useRef(0)

  useEffect(() => {
    return () => {
      runIdRef.current += 1
    }
  }, [])

  const patch = useCallback((partial: Partial<SearchState>) => {
    if ('searchId' in partial) searchIdRef.current = partial.searchId ?? null
    if ('viewState' in partial) viewRef.current = partial.viewState as SearchViewState
    if ('filters' in partial) filtersRef.current = partial.filters as Filters
    if ('page' in partial) pageRef.current = partial.page as number
    setState((prev) => ({ ...prev, ...partial }))
  }, [])

  const fetchResults = useCallback(
    async (runId: number, searchId: string, page: number): Promise<boolean> => {
      const f = filtersRef.current
      const res = await api.getResults(searchId, {
        page,
        perPage: PER_PAGE,
        sourceTypes: f.sourceTypes.length > 0 ? f.sourceTypes : undefined,
        time: f.time === 'all' ? undefined : f.time,
        duplicates: f.duplicates === 'all' ? undefined : f.duplicates,
        language: f.language || undefined,
      })
      if (runIdRef.current !== runId) return false
      patch({
        results: res.items,
        total: res.total,
        page: res.page,
        totalPages: Math.max(1, Math.ceil(res.total / PER_PAGE)),
      })
      return true
    },
    [patch],
  )

  const refreshHistory = useCallback(
    async (runId: number) => {
      try {
        const h = await api.getHistory(20)
        if (runIdRef.current !== runId) return
        patch({ history: h.items })
      } catch {
        // history is best-effort only
      }
    },
    [patch],
  )

  const pollUntilDone = useCallback(
    async (runId: number, searchId: string) => {
      seenCountRef.current = 0
      for (;;) {
        if (runIdRef.current !== runId) return
        await sleep(POLL_INTERVAL_MS)
        if (runIdRef.current !== runId) return

        let status: SearchStatusResponse
        try {
          status = await api.getSearch(searchId)
        } catch (err) {
          if (runIdRef.current !== runId) return
          patch(describeApiError(err))
          return
        }
        if (runIdRef.current !== runId) return

        patch({ sources: status.sources, query: status.query })

        if (status.status === 'running') {
          if (status.result_count > seenCountRef.current) {
            seenCountRef.current = status.result_count
            try {
              const ok = await fetchResults(runId, searchId, pageRef.current)
              if (!ok) return
            } catch {
              // transient failure while running — keep polling
            }
          }
          continue
        }

        if (status.status === 'failed') {
          patch({ viewState: 'failed', error: null })
          void refreshHistory(runId)
          return
        }

        const done = await fetchResults(runId, searchId, pageRef.current).catch(
          (err: unknown) => {
            if (runIdRef.current === runId) patch(describeApiError(err))
            return false
          },
        )
        if (!done || runIdRef.current !== runId) return
        patch({ viewState: status.status === 'completed' ? 'completed' : 'partial' })
        void refreshHistory(runId)
        return
      }
    },
    [fetchResults, patch, refreshHistory],
  )

  const startRun = useCallback(
    (query: string): number => {
      const runId = ++runIdRef.current
      filtersRef.current = { ...DEFAULT_FILTERS }
      pageRef.current = 1
      seenCountRef.current = 0
      patch({
        viewState: 'submitting',
        searchId: null,
        query,
        results: [],
        total: 0,
        page: 1,
        totalPages: 1,
        sources: [],
        error: null,
        filters: { ...DEFAULT_FILTERS },
        rateLimitRetryAt: null,
      })
      return runId
    },
    [patch],
  )

  const runSearch = useCallback(
    async (rawQuery: string) => {
      const query = rawQuery.trim()
      if (!query) return
      const runId = startRun(query)
      let created: { search_id: string }
      try {
        created = await api.createSearch(query)
      } catch (err) {
        if (runIdRef.current !== runId) return
        patch({
          ...describeApiError(err),
          rateLimitRetryAt:
            err instanceof ApiError && err.status === 429
              ? Date.now() + RATE_LIMIT_RETRY_MS
              : null,
        })
        return
      }
      if (runIdRef.current !== runId) return
      const searchId = created.search_id
      patch({ searchId, viewState: 'running' })
      if (typeof window !== 'undefined') {
        window.history.pushState({ s: searchId }, '', `?s=${encodeURIComponent(searchId)}`)
      }
      void refreshHistory(runId)
      await pollUntilDone(runId, searchId)
    },
    [patch, pollUntilDone, refreshHistory, startRun],
  )

  const openSearch = useCallback(
    async (searchId: string) => {
      const runId = ++runIdRef.current
      filtersRef.current = { ...DEFAULT_FILTERS }
      pageRef.current = 1
      seenCountRef.current = 0
      patch({
        viewState: 'running',
        searchId,
        query: '',
        results: [],
        total: 0,
        page: 1,
        totalPages: 1,
        sources: [],
        error: null,
        filters: { ...DEFAULT_FILTERS },
        rateLimitRetryAt: null,
      })

      let status: SearchStatusResponse
      try {
        status = await api.getSearch(searchId)
      } catch (err) {
        if (runIdRef.current !== runId) return
        patch(describeApiError(err))
        return
      }
      if (runIdRef.current !== runId) return
      patch({ query: status.query, sources: status.sources })

      if (status.status === 'running') {
        await pollUntilDone(runId, searchId)
        return
      }
      if (status.status === 'failed') {
        patch({ viewState: 'failed', error: null })
        return
      }

      const done = await fetchResults(runId, searchId, 1).catch((err: unknown) => {
        if (runIdRef.current === runId) patch(describeApiError(err))
        return false
      })
      if (!done || runIdRef.current !== runId) return
      patch({ viewState: status.status === 'completed' ? 'completed' : 'partial' })
      void refreshHistory(runId)
    },
    [fetchResults, patch, pollUntilDone, refreshHistory],
  )

  const setFilters = useCallback(
    (next: Partial<Filters>) => {
      const merged: Filters = { ...filtersRef.current, ...next }
      filtersRef.current = merged
      pageRef.current = 1
      setState((prev) => ({
        ...prev,
        filters: merged,
        page: 1,
        totalPages: Math.max(1, Math.ceil(prev.total / PER_PAGE)),
      }))
      const searchId = searchIdRef.current
      const view = viewRef.current
      if (
        searchId &&
        (view === 'running' || view === 'completed' || view === 'partial')
      ) {
        const runId = runIdRef.current
        void fetchResults(runId, searchId, 1).catch(() => {})
      }
    },
    [fetchResults],
  )

  const goToPage = useCallback(
    (page: number) => {
      const searchId = searchIdRef.current
      const view = viewRef.current
      if (!searchId || (view !== 'completed' && view !== 'partial')) return
      const clamped = Math.max(1, page)
      pageRef.current = clamped
      patch({ page: clamped })
      const runId = runIdRef.current
      void fetchResults(runId, searchId, clamped).catch(() => {})
    },
    [fetchResults, patch],
  )

  const reset = useCallback(() => {
    runIdRef.current += 1
    searchIdRef.current = null
    viewRef.current = 'idle'
    filtersRef.current = { ...DEFAULT_FILTERS }
    pageRef.current = 1
    setState((prev) => ({ ...initialState, history: prev.history }))
  }, [])

  useEffect(() => {
    const runId = runIdRef.current
    api
      .getHistory(20)
      .then((h) => {
        if (runIdRef.current !== runId) return
        patch({ history: h.items })
      })
      .catch(() => {})
  }, [patch])

  return {
    ...state,
    runSearch,
    openSearch,
    setFilters,
    goToPage,
    reset,
  }
}
