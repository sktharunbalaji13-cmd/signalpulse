const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

export type HealthResponse = {
  status: string
  service: string
  version: string
}

export type SearchCreated = {
  search_id: string
  status: string
}

export type SourceStatus = {
  name: string
  status: string
  result_count: number | null
  latency_ms: number | null
  error_type: string | null
  error: string | null
}

export type SearchStatusResponse = {
  search_id: string
  query: string
  status: 'running' | 'completed' | 'partial' | 'failed'
  created_at: string
  completed_at: string | null
  duration_ms: number | null
  result_count: number
  sources: SourceStatus[]
}

export type SearchResultItem = {
  source_type: string
  source_name: string
  title: string
  description: string | null
  url: string
  author: string | null
  published_at: string | null
  retrieved_at: string
  language: string | null
  is_duplicate: boolean
  duplicate_group_id: string | null
}

export type SearchResultsResponse = {
  total: number
  page: number
  per_page: number
  items: SearchResultItem[]
}

export type SearchHistoryItem = {
  search_id: string
  query: string
  status: 'running' | 'completed' | 'partial' | 'failed'
  created_at: string
  completed_at: string | null
  duration_ms: number | null
  result_count: number
}

export type SearchHistoryResponse = {
  items: SearchHistoryItem[]
}

export type ResultsOptions = {
  page?: number
  perPage?: number
  sourceTypes?: string[]
  time?: '24h' | '7d' | '30d'
  duplicates?: 'canonical'
  language?: string
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    throw new ApiError(response.status, `API request failed with status ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  getHealth(): Promise<HealthResponse> {
    return request('/api/v1/health')
  },

  createSearch(query: string, windowHours?: number): Promise<SearchCreated> {
    const body: { query: string; window_hours?: number } = { query }
    if (windowHours !== undefined) {
      body.window_hours = windowHours
    }
    return request('/api/v1/searches', { method: 'POST', body: JSON.stringify(body) })
  },

  getSearch(searchId: string): Promise<SearchStatusResponse> {
    return request(`/api/v1/searches/${searchId}`)
  },

  getResults(searchId: string, options: ResultsOptions = {}): Promise<SearchResultsResponse> {
    const params = new URLSearchParams()
    params.set('page', String(options.page ?? 1))
    params.set('per_page', String(options.perPage ?? 20))
    for (const sourceType of options.sourceTypes ?? []) {
      params.append('source_type', sourceType)
    }
    if (options.time) {
      params.set('time', options.time)
    }
    if (options.duplicates) {
      params.set('duplicates', options.duplicates)
    }
    if (options.language) {
      params.set('language', options.language)
    }
    const qs = params.toString()
    return request(`/api/v1/searches/${searchId}/results${qs ? `?${qs}` : ''}`)
  },

  getHistory(limit = 20): Promise<SearchHistoryResponse> {
    return request(`/api/v1/searches?limit=${limit}`)
  },
}
