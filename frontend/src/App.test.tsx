import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { api } from './api/client'
import { makeResult, makeSearchStatus } from './test/factories'

vi.mock('./api/client', () => ({
  api: {
    getHealth: vi.fn(),
    createSearch: vi.fn(),
    getSearch: vi.fn(),
    getResults: vi.fn(),
  },
}))

const mockedApi = vi.mocked(api)

function mockCompletedSearch() {
  mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
  let calls = 0
  mockedApi.getSearch.mockImplementation(async () => {
    calls += 1
    return makeSearchStatus({ status: calls >= 3 ? 'completed' : 'running' })
  })
  mockedApi.getResults.mockResolvedValue({
    total: 1,
    page: 1,
    per_page: 20,
    items: [makeResult()],
  })
  return { pollCalls: () => calls }
}

beforeEach(() => {
  vi.resetAllMocks()
  mockedApi.getHealth.mockResolvedValue({ status: 'ok', service: 'signalpulse-api', version: '0.1.0' })
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'ok', service: 'signalpulse-api', version: '0.1.0' }),
    }),
  )
})

describe('App', () => {
  it('renders the search input', () => {
    render(<App />)
    expect(screen.getByLabelText('Search topic')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Search' })).toBeInTheDocument()
  })

  it('rejects an empty query without calling the API', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), '   ')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('Enter a query to search.')).toBeInTheDocument()
    expect(mockedApi.createSearch).not.toHaveBeenCalled()
  })

  it('submits the query and renders results', async () => {
    mockCompletedSearch()
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'artificial intelligence')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText(/Results for:/, undefined, { timeout: 5000 })).toBeInTheDocument()
    expect(mockedApi.createSearch).toHaveBeenCalledWith('artificial intelligence')
    expect(mockedApi.getResults).toHaveBeenCalledWith('s1')
    expect(screen.getByText('1 result')).toBeInTheDocument()
    expect(screen.getByText('Artificial intelligence')).toBeInTheDocument()
  })

  it('shows a searching state while the search runs', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue(makeSearchStatus({ status: 'running' }))
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(screen.getByText('Searching…', { selector: 'p.status-text' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Searching…' })).toBeDisabled()
  })

  it('shows an error when the search fails', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue(makeSearchStatus({ status: 'failed' }))
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText(/Search failed\./, undefined, { timeout: 5000 })).toBeInTheDocument()
  })

  it('shows available results when the status is partial', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue(makeSearchStatus({ status: 'partial' }))
    mockedApi.getResults.mockResolvedValue({
      total: 1,
      page: 1,
      per_page: 20,
      items: [makeResult()],
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(
      await screen.findByText(/Some sources were unavailable/, undefined, { timeout: 5000 }),
    ).toBeInTheDocument()
    expect(screen.getByText('Artificial intelligence')).toBeInTheDocument()
  })

  it('stops polling once the search completes', async () => {
    const { pollCalls } = mockCompletedSearch()
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await screen.findByText(/Results for:/, undefined, { timeout: 5000 })
    const callsAfterCompletion = pollCalls()
    expect(callsAfterCompletion).toBe(3)

    await new Promise((resolve) => setTimeout(resolve, 2000))
    expect(pollCalls()).toBe(callsAfterCompletion)
  })
})
