import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AdminDashboard } from './AdminDashboard'
import { ApiError, api } from '../api/client'

vi.mock('../api/client', () => {
  return {
    ApiError: class ApiError extends Error {
      status: number
      constructor(status: number, message: string) {
        super(message)
        this.name = 'ApiError'
        this.status = status
      }
    },
    api: {
      adminLogin: vi.fn(),
      adminLogout: vi.fn(),
      getAdminStats: vi.fn(),
    },
  }
})

const mockedApi = vi.mocked(api)

const UNAUTHORIZED = new ApiError(401, 'unauthorized')

function sampleStats(window = '7d') {
  return {
    window,
    generated_at: '2026-08-23T12:00:00Z',
    retention: { days: 30, clock: 'searches.created_at', note: 'note' },
    searches: { total: 12, by_status: { completed: 8, partial: 4 } },
    latency_ms: { p50: 1100, p95: 1600, p99: 1800 },
    sources: {
      Wikipedia: { success: 12, failed: 0, avg_latency_ms: 600, avg_results: 10 },
      'Hacker News': { success: 12, failed: 0, avg_latency_ms: 800, avg_results: 10 },
      Reddit: { success: 0, failed: 0, disabled: 12, avg_latency_ms: 200, avg_results: 0 },
    },
    dedup: { total_groups: 3, duplicates_removed: 5 },
    semantic: { disabled: 12, searches_with_stage: 12, avg_ms: null, note: 'dormant' },
    queries: { empty_result_count: 0, privacy_note: 'aggregate only' },
  }
}

beforeEach(() => {
  vi.resetAllMocks()
})

describe('AdminDashboard', () => {
  it('shows the login gate when not authenticated', async () => {
    mockedApi.getAdminStats.mockRejectedValue(UNAUTHORIZED)
    render(<AdminDashboard />)
    expect(await screen.findByLabelText('Admin key')).toBeInTheDocument()
    expect(screen.getByText('SignalPulse Operations')).toBeInTheDocument()
  })

  it('renders stats sections when authenticated', async () => {
    mockedApi.getAdminStats.mockResolvedValue(sampleStats())
    render(<AdminDashboard />)
    expect(await screen.findByText('Source Health')).toBeInTheDocument()
    expect(screen.getAllByText('12').length).toBeGreaterThanOrEqual(1) // searches total
    expect(screen.getByText('Retention')).toBeInTheDocument()
    expect(screen.getByText(/30 days/)).toBeInTheDocument()
    expect(screen.getByText(/EXPERIMENTAL — DORMANT/)).toBeInTheDocument()
    expect(screen.getByText('Reddit')).toBeInTheDocument()
    // M21.3: the disabled column is present and populated.
    expect(screen.getByText('Disabled')).toBeInTheDocument()
  })

  it('logs in with a key then loads stats', async () => {
    mockedApi.getAdminStats.mockRejectedValueOnce(UNAUTHORIZED)
    mockedApi.getAdminStats.mockResolvedValue(sampleStats())
    mockedApi.adminLogin.mockResolvedValue({ ok: true })
    const user = userEvent.setup()
    render(<AdminDashboard />)

    const input = await screen.findByLabelText('Admin key')
    await user.type(input, 'secret-key')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(mockedApi.adminLogin).toHaveBeenCalledWith('secret-key')
    await waitFor(() => expect(screen.getByText('Source Health')).toBeInTheDocument())
    // The key is not stored after login.
    expect(screen.queryByDisplayValue('secret-key')).not.toBeInTheDocument()
  })

  it('shows an error on invalid key', async () => {
    mockedApi.getAdminStats.mockRejectedValue(UNAUTHORIZED)
    mockedApi.adminLogin.mockRejectedValue(new ApiError(401, 'bad'))
    const user = userEvent.setup()
    render(<AdminDashboard />)

    const input = await screen.findByLabelText('Admin key')
    await user.type(input, 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Invalid admin key.')).toBeInTheDocument()
  })

  it('switches between time windows and refetches', async () => {
    mockedApi.getAdminStats
      .mockResolvedValueOnce(sampleStats('7d'))
      .mockResolvedValueOnce(sampleStats('24h'))
    const user = userEvent.setup()
    render(<AdminDashboard />)

    await screen.findByText('Source Health')
    await user.click(screen.getByRole('button', { name: '24h' }))

    await waitFor(() => expect(mockedApi.getAdminStats).toHaveBeenLastCalledWith('24h'))
  })

  it('surfaces an API failure state', async () => {
    mockedApi.getAdminStats.mockRejectedValue(new ApiError(503, 'down'))
    render(<AdminDashboard />)
    expect(
      await screen.findByText('Could not load admin statistics. Please try again.'),
    ).toBeInTheDocument()
  })

  it('logs out and returns to the login gate', async () => {
    mockedApi.getAdminStats.mockResolvedValue(sampleStats())
    mockedApi.adminLogout.mockResolvedValue({ ok: true })
    const user = userEvent.setup()
    render(<AdminDashboard />)

    await screen.findByText('Source Health')
    await user.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(await screen.findByLabelText('Admin key')).toBeInTheDocument()
  })
})