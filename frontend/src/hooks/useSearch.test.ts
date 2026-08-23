import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useSearch } from './useSearch'

vi.mock('../api/client', () => {
  class MockApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.name = 'ApiError'
      this.status = status
    }
  }
  return {
    ApiError: MockApiError,
    api: {
      getHealth: vi.fn(),
      createSearch: vi.fn(),
      getSearch: vi.fn(),
      getResults: vi.fn(),
    },
  }
})

import { ApiError, api } from '../api/client'

const mockedApi = vi.mocked(api)

function makeItems(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    source_type: 'news',
    source_name: 'The Guardian',
    title: `Result ${i + 1}`,
    description: null,
    url: `https://example.com/${i + 1}`,
    author: null,
    published_at: null,
    retrieved_at: '2026-08-19T12:00:00Z',
    language: 'en',
    is_duplicate: false,
    duplicate_group_id: null,
  }))
}

function resultsResponse(total: number, page = 1) {
  return {
    total,
    page,
    per_page: 20,
    items: makeItems(Math.min(total, 20)),
  }
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

/** jsdom's built-in localStorage isn't functional under this runner; install
 *  a minimal working stub so storage-dependent behavior can be exercised. */
function installStorageStub(): void {
  const store = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
      setItem: (key: string, value: string) => void store.set(key, String(value)),
      removeItem: (key: string) => void store.delete(key),
      clear: () => store.clear(),
    },
  })
}

beforeEach(() => {
  vi.resetAllMocks()
})

describe('useSearch', () => {
  it('runs a search to completion and fetches ranked results', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue({
      search_id: 's1',
      query: 'ai',
      status: 'completed',
      created_at: '2026-08-19T12:00:00Z',
      completed_at: null,
      duration_ms: null,
      result_count: 2,
      sources: [],
    })
    mockedApi.getResults.mockResolvedValue(resultsResponse(2))

    const { result } = renderHook(() => useSearch())
    await act(async () => {
      await result.current.runSearch('ai')
    })

    expect(result.current.viewState).toBe('completed')
    expect(result.current.searchId).toBe('s1')
    expect(result.current.results).toHaveLength(2)
    expect(result.current.total).toBe(2)
    expect(mockedApi.getResults).toHaveBeenCalledWith(
      's1',
      expect.objectContaining({ page: 1, perPage: 20 }),
    )
  })

  it('reports a partial search with results', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue({
      search_id: 's1',
      query: 'ai',
      status: 'partial',
      created_at: '2026-08-19T12:00:00Z',
      completed_at: null,
      duration_ms: null,
      result_count: 1,
      sources: [],
    })
    mockedApi.getResults.mockResolvedValue(resultsResponse(1))

    const { result } = renderHook(() => useSearch())
    await act(async () => {
      await result.current.runSearch('ai')
    })

    expect(result.current.viewState).toBe('partial')
    expect(result.current.total).toBe(1)
  })

  it('marks a fully failed search without fetching results', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue({
      search_id: 's1',
      query: 'ai',
      status: 'failed',
      created_at: '2026-08-19T12:00:00Z',
      completed_at: null,
      duration_ms: null,
      result_count: 0,
      sources: [],
    })

    const { result } = renderHook(() => useSearch())
    await act(async () => {
      await result.current.runSearch('ai')
    })

    expect(result.current.viewState).toBe('failed')
    expect(mockedApi.getResults).not.toHaveBeenCalled()
  })

  it('surfaces a 429 as a rate-limited state with a retry timestamp', async () => {
    mockedApi.createSearch.mockRejectedValue(new ApiError(429, 'too many'))

    const { result } = renderHook(() => useSearch())
    await act(async () => {
      await result.current.runSearch('ai')
    })

    expect(result.current.viewState).toBe('error-rate-limited')
    expect(result.current.rateLimitRetryAt).not.toBeNull()
    expect(result.current.rateLimitRetryAt!).toBeGreaterThan(Date.now() - 1000)
  })

  it('surfaces network failures', async () => {
    mockedApi.createSearch.mockRejectedValue(new TypeError('fetch failed'))

    const { result } = renderHook(() => useSearch())
    await act(async () => {
      await result.current.runSearch('ai')
    })

    expect(result.current.viewState).toBe('error-network')
  })

  it('stops polling after unmount', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue({
      search_id: 's1',
      query: 'ai',
      status: 'running',
      created_at: '2026-08-19T12:00:00Z',
      completed_at: null,
      duration_ms: null,
      result_count: 0,
      sources: [],
    })

    const { result, unmount } = renderHook(() => useSearch())
    act(() => {
      void result.current.runSearch('ai')
    })
    await waitFor(() => expect(mockedApi.getSearch).toHaveBeenCalledTimes(1))

    unmount()
    const callsAtUnmount = mockedApi.getSearch.mock.calls.length
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1700))
    })
    expect(mockedApi.getSearch.mock.calls.length).toBe(callsAtUnmount)
  }, 10_000)

  it('refetches results progressively while running', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    let polls = 0
    mockedApi.getSearch.mockImplementation(async () => {
      polls += 1
      const count = polls === 1 ? 0 : 5
      return {
        search_id: 's1',
        query: 'ai',
        status: polls >= 3 ? 'completed' : 'running',
        created_at: '2026-08-19T12:00:00Z',
        completed_at: null,
        duration_ms: null,
        result_count: count,
        sources: [],
      }
    })
    mockedApi.getResults.mockResolvedValue(resultsResponse(5))

    const { result } = renderHook(() => useSearch())
    await act(async () => {
      await result.current.runSearch('ai')
    })

    await waitFor(() => expect(result.current.viewState).toBe('completed'))
    // once mid-run (count rose to 5) plus the terminal fetch
    expect(mockedApi.getResults).toHaveBeenCalledTimes(2)
    expect(result.current.total).toBe(5)
  })

  it('refetches results when filters change, resetting to page 1', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue({
      search_id: 's1',
      query: 'ai',
      status: 'completed',
      created_at: '2026-08-19T12:00:00Z',
      completed_at: null,
      duration_ms: null,
      result_count: 3,
      sources: [],
    })
    mockedApi.getResults.mockResolvedValue(resultsResponse(3))

    const { result } = renderHook(() => useSearch())
    await act(async () => {
      await result.current.runSearch('ai')
    })
    mockedApi.getResults.mockClear()

    await act(async () => {
      result.current.setFilters({ time: '24h', sourceTypes: ['news'] })
    })
    await waitFor(() => expect(mockedApi.getResults).toHaveBeenCalledTimes(1))
    expect(mockedApi.getResults).toHaveBeenCalledWith(
      's1',
      expect.objectContaining({ time: '24h', sourceTypes: ['news'], page: 1 }),
    )
    expect(result.current.filters.time).toBe('24h')
  })

  it('paginates within the same search', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue({
      search_id: 's1',
      query: 'ai',
      status: 'completed',
      created_at: '2026-08-19T12:00:00Z',
      completed_at: null,
      duration_ms: null,
      result_count: 45,
      sources: [],
    })
    mockedApi.getResults.mockImplementation(async (_id, options) =>
      resultsResponse(45, options?.page ?? 1),
    )

    const { result } = renderHook(() => useSearch())
    await act(async () => {
      await result.current.runSearch('ai')
    })
    expect(result.current.totalPages).toBe(3)
    mockedApi.getResults.mockClear()

    await act(async () => {
      result.current.goToPage(2)
    })
    await waitFor(() => expect(mockedApi.getResults).toHaveBeenCalledTimes(1))
    expect(mockedApi.getResults).toHaveBeenCalledWith(
      's1',
      expect.objectContaining({ page: 2 }),
    )
    expect(result.current.page).toBe(2)
  })

  it('restores an existing search by id', async () => {
    mockedApi.getSearch.mockResolvedValue({
      search_id: 'old',
      query: 'quantum',
      status: 'completed',
      created_at: '2026-08-19T12:00:00Z',
      completed_at: null,
      duration_ms: null,
      result_count: 4,
      sources: [],
    })
    mockedApi.getResults.mockResolvedValue(resultsResponse(4))

    const { result } = renderHook(() => useSearch())
    await act(async () => {
      await result.current.openSearch('old')
    })

    expect(result.current.viewState).toBe('completed')
    expect(result.current.query).toBe('quantum')
    expect(result.current.total).toBe(4)
  })

  it('resets back to the landing state, keeping local history', async () => {
    // M19.1: history is loaded from localStorage, not the server.
    installStorageStub()
    window.localStorage.setItem(
      'signalpulse:history',
      JSON.stringify([
        {
          search_id: 'h1',
          query: 'history',
          status: 'completed',
          created_at: '2026-08-19T12:00:00Z',
          result_count: 2,
        },
      ]),
    )
    const { result } = renderHook(() => useSearch())
    await waitFor(() => expect(result.current.history).toHaveLength(1))
    expect(result.current.history[0].query).toBe('history')

    act(() => {
      result.current.reset()
    })
    expect(result.current.viewState).toBe('idle')
    expect(result.current.history).toHaveLength(1)
    await settle()
  })

  it('records searches locally and finalizes their status', async () => {
    installStorageStub()
    mockedApi.createSearch.mockResolvedValue({ search_id: 'loc1', status: 'running' })
    let calls = 0
    mockedApi.getSearch.mockImplementation(async () => {
      calls += 1
      return {
        search_id: 'loc1',
        query: 'local query',
        status: calls >= 2 ? ('completed' as const) : ('running' as const),
        created_at: '2026-08-23T12:00:00Z',
        completed_at: null,
        duration_ms: null,
        result_count: calls >= 2 ? 3 : 0,
        sources: [],
      }
    })
    mockedApi.getResults.mockResolvedValue(resultsResponse(3))

    const { result } = renderHook(() => useSearch())
    await act(async () => {
      await result.current.runSearch('local query')
    })

    await waitFor(() =>
      expect(result.current.history.some((h) => h.search_id === 'loc1')).toBe(true),
    )
    const entry = result.current.history.find((h) => h.search_id === 'loc1')
    expect(entry?.query).toBe('local query')
    expect(entry?.status).toBe('completed')
    expect(entry?.result_count).toBe(3)
    // Nothing is fetched from the server history listing anymore.
  })

  it('tolerates corrupt localStorage on startup', () => {
    installStorageStub()
    window.localStorage.setItem('signalpulse:history', '{not-json')
    const { result } = renderHook(() => useSearch())
    expect(result.current.history).toHaveLength(0)
  })
})
