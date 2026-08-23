import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { LocalHistoryItem } from '../utils/historyStorage'
import { SearchHistory } from './SearchHistory'

function makeItem(overrides: Partial<LocalHistoryItem> = {}): LocalHistoryItem {
  return {
    search_id: 's1',
    query: 'artificial intelligence',
    status: 'completed',
    created_at: '2026-08-19T12:00:00Z',
    result_count: 7,
    ...overrides,
  }
}

describe('SearchHistory', () => {
  it('shows an empty message when there is no history', () => {
    render(<SearchHistory items={[]} onSelect={vi.fn()} />)
    expect(screen.getByText('No searches yet.')).toBeInTheDocument()
  })

  it('renders queries with status, count and date', () => {
    render(
      <SearchHistory
        items={[makeItem(), makeItem({ search_id: 's2', query: 'quantum', status: 'partial', result_count: 1 })]}
        onSelect={vi.fn()}
      />,
    )
    expect(screen.getByText('artificial intelligence')).toBeInTheDocument()
    expect(screen.getByText(/completed · 7 results/)).toBeInTheDocument()
    expect(screen.getByText(/partial · 1 result/)).toBeInTheDocument()
  })

  it('selects a previous search on click', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<SearchHistory items={[makeItem()]} onSelect={onSelect} />)
    await user.click(screen.getByRole('button', { name: /artificial intelligence/ }))
    expect(onSelect).toHaveBeenCalledWith('s1')
  })
})
