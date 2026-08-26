import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { DEFAULT_FILTERS, type Filters } from '../hooks/useSearch'
import { FilterRefine } from './FilterRefine'

function renderRefine(filters: Filters = DEFAULT_FILTERS) {
  const onChange = vi.fn()
  render(<FilterRefine filters={filters} onChange={onChange} />)
  return { onChange }
}

describe('FilterRefine', () => {
  it('is collapsed by default with the baseline summary', () => {
    renderRefine()
    const head = screen.getByRole('button', { name: /Filter & refine/i })
    expect(head).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('All sources · All time · All duplicates')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: 'news' })).not.toBeInTheDocument()
  })

  it('expands into the existing filter controls on tap', async () => {
    const user = userEvent.setup()
    renderRefine()
    const head = screen.getByRole('button', { name: /Filter & refine/i })
    await user.click(head)
    expect(head).toHaveAttribute('aria-expanded', 'true')
    const region = screen.getByRole('region', { name: /Filter & refine/i })
    expect(within(region).getByRole('checkbox', { name: 'news' })).toBeInTheDocument()
    expect(within(region).getByLabelText('Time')).toBeInTheDocument()
  })

  it('shows an active-filter badge and summary when filters are active', () => {
    renderRefine({ ...DEFAULT_FILTERS, sourceTypes: ['news'], time: '7d' })
    expect(screen.getByText('2 active')).toBeInTheDocument()
    expect(screen.getByText('news · 7d · All duplicates')).toBeInTheDocument()
  })

  it('reuses the existing filter controls and forwards changes', async () => {
    const user = userEvent.setup()
    const { onChange } = renderRefine()
    await user.click(screen.getByRole('button', { name: /Filter & refine/i }))
    await user.click(
      within(screen.getByRole('region', { name: /Filter & refine/i })).getByRole(
        'checkbox',
        { name: 'news' },
      ),
    )
    expect(onChange).toHaveBeenCalledWith({ sourceTypes: ['news'] })
  })

  it('keeps selected filters selected when re-opened', async () => {
    const user = userEvent.setup()
    render(<FilterRefine filters={{ ...DEFAULT_FILTERS, sourceTypes: ['news'] }} onChange={vi.fn()} />)
    const head = screen.getByRole('button', { name: /Filter & refine/i })
    await user.click(head)
    const news = within(screen.getByRole('region', { name: /Filter & refine/i })).getByRole(
      'checkbox',
      { name: 'news' },
    )
    expect(news).toBeChecked()
    await user.click(head)
    await user.click(head)
    expect(
      within(screen.getByRole('region', { name: /Filter & refine/i })).getByRole(
        'checkbox',
        { name: 'news' },
      ),
    ).toBeChecked()
  })
})