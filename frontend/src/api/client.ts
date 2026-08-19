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
}

export type SearchResultsResponse = {
  total: number
  page: number
  per_page: number
  items: SearchResultItem[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    throw new Error(`API request failed with status ${response.status}`)
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

  getResults(searchId: string, page = 1, perPage = 20): Promise<SearchResultsResponse> {
    return request(`/api/v1/searches/${searchId}/results?page=${page}&per_page=${perPage}`)
  },
}