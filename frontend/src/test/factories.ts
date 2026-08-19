import type { SearchResultItem, SearchStatusResponse } from '../api/client'

export function makeResult(overrides: Partial<SearchResultItem> = {}): SearchResultItem {
  return {
    source_type: 'reference',
    source_name: 'Wikipedia',
    title: 'Artificial intelligence',
    description: 'Some description text.',
    url: 'https://en.wikipedia.org/wiki/Artificial_intelligence',
    author: null,
    published_at: null,
    retrieved_at: '2026-08-19T12:00:00Z',
    language: 'en',
    ...overrides,
  }
}

export function makeSearchStatus(
  overrides: Partial<SearchStatusResponse> = {},
): SearchStatusResponse {
  return {
    search_id: 's1',
    query: 'artificial intelligence',
    status: 'running',
    created_at: '2026-08-19T12:00:00Z',
    completed_at: null,
    duration_ms: null,
    result_count: 0,
    sources: [],
    ...overrides,
  }
}