import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { ApiError, api } from './api/client'
import { makeResult, makeSearchStatus } from './test/factories'

vi.mock('./api/client', () => {
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

const mockedApi = vi.mocked(api)

function mockCompletedSearch(total = 1) {
  mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
  let calls = 0
  mockedApi.getSearch.mockImplementation(async () => {
    calls += 1
    return makeSearchStatus({
      status: calls >= 2 ? 'completed' : 'running',
      result_count: calls >= 2 ? total : 0,
    })
  })
  mockedApi.getResults.mockImplementation(async (_id, options) => ({
    total,
    page: options?.page ?? 1,
    per_page: 20,
    items: [makeResult()],
  }))
  return { pollCalls: () => calls }
}

beforeEach(() => {
  vi.resetAllMocks()
  window.history.replaceState({}, '', '/')
  mockedApi.getHealth.mockResolvedValue({
    status: 'ok',
    service: 'signalpulse-api',
    version: '0.1.0',
  })
})

/** The results heading renders while still running (progressive UX), so
 *  terminal-sensitive tests must wait for the fetched-result count instead.
 *  Two 700 ms poll ticks exceed RTL's default 1 s timeout, hence 5 s. */
function waitForTerminalResults(total: number) {
    if (total === 0) {
      return screen.findByText('No results found.', {}, { timeout: 5000 })
    }
    return screen.findByText(new RegExp(`^${total} SIGNALS$`), {}, { timeout: 5000 })
  }

describe('App', () => {
  it('renders the search input and example queries', () => {
    render(<App />)
    expect(screen.getByLabelText('Search topic')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Search' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'artificial intelligence' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'quantum computing' })).toBeInTheDocument()
  })

  it('rejects an empty query without calling the API', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), '   ')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('Enter a query to search.')).toBeInTheDocument()
    expect(mockedApi.createSearch).not.toHaveBeenCalled()
  })

  it('runs an example search from the landing state', async () => {
    mockCompletedSearch(1)
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: 'quantum computing' }))

    expect(mockedApi.createSearch).toHaveBeenCalledWith('quantum computing')
    await waitForTerminalResults(1)
    expect(screen.getByText(/Results for:/)).toBeInTheDocument()
  })

  it('submits the query and renders ranked results', async () => {
    mockCompletedSearch(1)
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'artificial intelligence')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitForTerminalResults(1)
    expect(mockedApi.createSearch).toHaveBeenCalledWith('artificial intelligence')
    expect(mockedApi.getResults).toHaveBeenCalledWith(
      's1',
      expect.objectContaining({ page: 1 }),
    )
    expect(screen.getByText('#01')).toBeInTheDocument()
    expect(screen.getByText(/Results for:/)).toBeInTheDocument()
  })

  it('shows author and duplicate badge on cards', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue(
      makeSearchStatus({ status: 'completed', result_count: 1 }),
    )
    mockedApi.getResults.mockResolvedValue({
      total: 1,
      page: 1,
      per_page: 20,
      items: [
        makeResult({
          source_type: 'news',
          source_name: 'The Guardian',
          title: 'Guardian article',
          author: 'Jane Reporter',
          is_duplicate: true,
        }),
      ],
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('By Jane Reporter', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText('duplicate')).toBeInTheDocument()
  })

  it('shows a searching state while the search runs', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockImplementation(() => new Promise(() => undefined))
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(
      await screen.findByText(/^Searching/, { selector: '.notice p' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Searching|Search/ })).toBeDisabled()
  })

  it('shows an error when every source fails', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue(makeSearchStatus({ status: 'failed' }))
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText(/Every source was unavailable/)).toBeInTheDocument()
  })

  it('surfaces a 429 rate-limit response distinctly and disables re-submit', async () => {
    mockedApi.createSearch.mockRejectedValue(new ApiError(429, 'too many searches'))
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText(/Too many searches/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled()
  })

  it('shows an empty-results state', async () => {
    mockCompletedSearch(0)
    mockedApi.getResults.mockClear()
    mockedApi.getResults.mockResolvedValue({
      total: 0,
      page: 1,
      per_page: 20,
      items: [],
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('No results found.', {}, { timeout: 5000 })).toBeInTheDocument()
  })

  it('shows a filter-aware empty message when filters are active', async () => {
    mockCompletedSearch(0)
    mockedApi.getResults.mockClear()
    mockedApi.getResults.mockResolvedValue({
      total: 0,
      page: 1,
      per_page: 20,
      items: [],
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await screen.findByText('No results found.', {}, { timeout: 5000 })

    await user.selectOptions(screen.getByLabelText('Time'), '7d')

    expect(await screen.findByText(/No results match these filters/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Reset filters' }))
    expect(await screen.findByText('No results found.', {}, { timeout: 5000 })).toBeInTheDocument()
  })

  it('shows skeleton placeholders while results are loading', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockImplementation(() => new Promise(() => undefined))
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findAllByTestId('result-skeleton')).toHaveLength(3)
  })

  it('applies the time filter as a query-time view', async () => {
    mockCompletedSearch(3)
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitForTerminalResults(3)
    mockedApi.getResults.mockClear()

    await user.selectOptions(screen.getByLabelText('Time'), '24h')

    await waitFor(() =>
      expect(mockedApi.getResults).toHaveBeenCalledWith(
        's1',
        expect.objectContaining({ time: '24h', page: 1 }),
      ),
    )
    expect(
      screen.getByRole('button', { name: 'Remove time filter 24h' }),
    ).toBeInTheDocument()
  })

  it('paginates through results', async () => {
    mockCompletedSearch(45)
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitForTerminalResults(45)
    mockedApi.getResults.mockClear()

    await user.click(screen.getByRole('button', { name: /next/i }))

    await waitFor(() =>
      expect(mockedApi.getResults).toHaveBeenCalledWith(
        's1',
        expect.objectContaining({ page: 2 }),
      ),
    )
    expect(screen.getByText('Page 2 of 3')).toBeInTheDocument()
  })

  it('shows a per-source status summary on completion', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue(
      makeSearchStatus({
        status: 'completed',
        sources: [
          { name: 'Wikipedia', status: 'success', result_count: 10, latency_ms: 320, error_type: null, error: null },
          { name: 'The Guardian', status: 'success', result_count: 8, latency_ms: 410, error_type: null, error: null },
        ],
      }),
    )
    mockedApi.getResults.mockResolvedValue({
      total: 2,
      page: 1,
      per_page: 20,
      items: [
        makeResult(),
        makeResult({ source_type: 'news', source_name: 'The Guardian', title: 'Guardian article' }),
      ],
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(
      await screen.findByText(/✓ Wikipedia/, {}, { timeout: 5000 }),
    ).toBeInTheDocument()
    expect(screen.getByText('10 results')).toBeInTheDocument()
    expect(screen.getByText('320 ms')).toBeInTheDocument()
    expect(screen.getByText(/✓ The Guardian/)).toBeInTheDocument()
    expect(screen.getByText('8 results')).toBeInTheDocument()
    expect(screen.getByText('NEWS')).toBeInTheDocument()
  })

  it('represents an unconfigured source as a source failure, not a global failure', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue(
      makeSearchStatus({
        status: 'partial',
        sources: [
          { name: 'Wikipedia', status: 'success', result_count: 10, latency_ms: 320, error_type: null, error: null },
          {
            name: 'Reddit',
            status: 'failed',
            result_count: null,
            latency_ms: 90,
            error_type: 'failed',
            error: 'Reddit credentials are not configured',
          },
        ],
      }),
    )
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

    expect(await screen.findByText(/⚠ Reddit/)).toBeInTheDocument()
    expect(await screen.findByText(/Partial Source Coverage/i)).toBeInTheDocument()
    expect(screen.getByText('Artificial intelligence')).toBeInTheDocument()
  })

  it('renders a disabled source neutrally without a partial banner (M21.3)', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue(
      makeSearchStatus({
        status: 'completed',
        result_count: 2,
        sources: [
          { name: 'Wikipedia', status: 'success', result_count: 10, latency_ms: 320, error_type: null, error: null },
          { name: 'The Guardian', status: 'success', result_count: 8, latency_ms: 410, error_type: null, error: null },
          { name: 'Hacker News', status: 'success', result_count: 5, latency_ms: 500, error_type: null, error: null },
          {
            name: 'Reddit',
            status: 'disabled',
            result_count: null,
            latency_ms: null,
            error_type: 'disabled',
            error: 'source is not configured',
          },
        ],
      }),
    )
    mockedApi.getResults.mockResolvedValue({
      total: 2,
      page: 1,
      per_page: 20,
      items: [makeResult(), makeResult({ source_name: 'The Guardian', title: 'G2' })],
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText(/○ Reddit/, {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText('disabled')).toBeInTheDocument()
    // Disabled is not a failure: no partial-coverage banner.
    expect(screen.queryByText(/Partial Source Coverage/i)).not.toBeInTheDocument()
    // All healthy enabled sources still render normally.
    expect(screen.getByText(/✓ Wikipedia/)).toBeInTheDocument()
  })

  it('restores a previous search from the shareable URL', async () => {
    window.history.pushState({}, '', '/?s=old-search')
    mockedApi.getSearch.mockResolvedValue(
      makeSearchStatus({
        search_id: 'old-search',
        query: 'quantum computing',
        status: 'completed',
        result_count: 4,
      }),
    )
    mockedApi.getResults.mockResolvedValue({
      total: 4,
      page: 1,
      per_page: 20,
      items: [makeResult()],
    })
    render(<App />)

    expect(await screen.findByText(/Results for:/)).toBeInTheDocument()
    expect(mockedApi.getSearch).toHaveBeenCalledWith('old-search')
    expect(screen.getByText(/quantum computing/)).toBeInTheDocument()
    expect(mockedApi.getResults).toHaveBeenCalledWith(
      'old-search',
      expect.objectContaining({ page: 1 }),
    )
  })

  it('stops polling once the search completes', async () => {
    const { pollCalls } = mockCompletedSearch()
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => expect(pollCalls()).toBeGreaterThanOrEqual(2), { timeout: 5000 })
    const callsAfterCompletion = pollCalls()

    await new Promise((resolve) => setTimeout(resolve, 1600))
    expect(pollCalls()).toBe(callsAfterCompletion)
  })

  it('renders the footer with contact links', () => {
    render(<App />)
    const emailLink = screen.getByRole('link', { name: /sktharunbalaji13@gmail.com/ })
    expect(emailLink).toHaveAttribute('href', 'mailto:sktharunbalaji13@gmail.com')
    expect(screen.getByRole('link', { name: /sktharunbalaji13-cmd/ })).toHaveAttribute(
      'href',
      'https://github.com/sktharunbalaji13-cmd',
    )
    expect(screen.getByRole('link', { name: /tharun balaji/i })).toHaveAttribute(
      'href',
      'https://www.linkedin.com/in/tharun-balaji-0ba196327/',
    )
  })

  it('provides a skip link and lands on main content (M23 FE-H)', () => {
    render(<App />)
    const skip = screen.getByRole('link', { name: 'Skip to content' })
    expect(skip).toHaveAttribute('href', '#main-content')
    expect(document.querySelector('main#main-content')).not.toBeNull()
  })

  it('shows the evidence-class strip with a dormant social class (M23 FE-B)', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue(
      makeSearchStatus({
        status: 'completed',
        result_count: 18,
        sources: [
          { name: 'Wikipedia', status: 'success', result_count: 10, latency_ms: 320, error_type: null, error: null },
          { name: 'The Guardian', status: 'success', result_count: 8, latency_ms: 410, error_type: null, error: null },
          { name: 'Reddit', status: 'disabled', result_count: null, latency_ms: null, error_type: 'disabled', error: null },
          { name: 'Bluesky', status: 'disabled', result_count: null, latency_ms: null, error_type: 'disabled', error: null },
        ],
      }),
    )
    mockedApi.getResults.mockResolvedValue({
      total: 18,
      page: 1,
      per_page: 20,
      items: [makeResult(), makeResult({ source_type: 'news', source_name: 'The Guardian', title: 'G2' })],
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Search topic'), 'ai')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('Reference', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText('· 10')).toBeInTheDocument()
    expect(screen.getByText('Social')).toBeInTheDocument()
    expect(screen.getAllByText('· dormant').length).toBeGreaterThan(0)
  })

  it('names missing evidence classes in the partial banner (M23 FE-F)', async () => {
    mockedApi.createSearch.mockResolvedValue({ search_id: 's1', status: 'running' })
    mockedApi.getSearch.mockResolvedValue(
      makeSearchStatus({
        status: 'partial',
        sources: [
          { name: 'Wikipedia', status: 'success', result_count: 10, latency_ms: 320, error_type: null, error: null },
          { name: 'YouTube', status: 'failed', result_count: null, latency_ms: 200, error_type: 'failed', error: 'boom' },
        ],
      }),
    )
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
      await screen.findByText(/Missing evidence classes: Video/, {}, { timeout: 5000 }),
    ).toBeInTheDocument()
  })
})
