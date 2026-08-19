import { useCallback, useEffect, useRef, useState } from 'react'

import { api, type SearchResultItem, type SearchStatusResponse, type SourceStatus } from '../api/client'

const POLL_INTERVAL_MS = 700

export type SearchViewState = 'idle' | 'searching' | 'completed' | 'partial' | 'failed'

export type SearchState = {
  viewState: SearchViewState
  query: string
  resultCount: number
  results: SearchResultItem[]
  sources: SourceStatus[]
  error: string | null
}

const initialState: SearchState = {
  viewState: 'idle',
  query: '',
  resultCount: 0,
  results: [],
  sources: [],
  error: null,
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

export function useSearch() {
  const [state, setState] = useState<SearchState>(initialState)
  const cancelledRef = useRef(false)

  useEffect(() => {
    return () => {
      cancelledRef.current = true
    }
  }, [])

  const runSearch = useCallback(async (rawQuery: string) => {
    const query = rawQuery.trim()
    if (!query) {
      return
    }
    cancelledRef.current = false
    setState({ ...initialState, viewState: 'searching', query })

    try {
      const created = await api.createSearch(query)
      let status: SearchStatusResponse['status'] = 'running'
      while (status === 'running' && !cancelledRef.current) {
        await sleep(POLL_INTERVAL_MS)
        if (cancelledRef.current) {
          return
        }
        const search = await api.getSearch(created.search_id)
        status = search.status
        if (status === 'running') {
          continue
        }
        if (status === 'failed') {
          setState((prev) => ({
            ...prev,
            viewState: 'failed',
            sources: search.sources,
            error: 'Search failed. The source may be unavailable; try again shortly.',
          }))
        } else {
          const results = await api.getResults(created.search_id)
          const viewState = status
          setState((prev) => ({
            ...prev,
            viewState,
            sources: search.sources,
            resultCount: results.total,
            results: results.items,
          }))
        }
      }
    } catch {
      if (!cancelledRef.current) {
        setState((prev) => ({
          ...prev,
          viewState: 'failed',
          error: 'Search failed. Could not reach the backend; try again shortly.',
        }))
      }
    }
  }, [])

  return { ...state, runSearch }
}