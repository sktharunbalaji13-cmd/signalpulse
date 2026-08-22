import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { DEFAULT_FILTERS, type Filters } from '../hooks/useSearch'
import { FilterBar } from './FilterBar'

function renderBar(overrides: Partial<Filters> = {}) {
  const onChange = vi.fn()
  render(<FilterBar filters={{ ...DEFAULT_FILTERS, ...overrides }} onChange={onChange} />)
  return { onChange }
}

describe('FilterBar', () => {
  it('toggles a source type on', async () => {
    const user = userEvent.setup()
    const { onChange } = renderBar()
    await user.click(screen.getByRole('checkbox', { name: 'news' }))
    expect(onChange).toHaveBeenCalledWith({ sourceTypes: ['news'] })
  })

  it('toggles a source type off', async () => {
    const user = userEvent.setup()
    const { onChange } = renderBar({ sourceTypes: ['news', 'social'] })
    await user.click(screen.getByRole('checkbox', { name: 'news' }))
    expect(onChange).toHaveBeenCalledWith({ sourceTypes: ['social'] })
  })

  it('emits only backend-supported time windows', async () => {
    const user = userEvent.setup()
    const { onChange } = renderBar()
    for (const value of ['24h', '7d', '30d', 'all']) {
      await user.selectOptions(screen.getByLabelText('Time'), value)
    }
    const calls = onChange.mock.calls.map((c) => (c[0] as { time: string }).time)
    expect(calls).toEqual(['24h', '7d', '30d', 'all'])
  })

  it('emits duplicates=canonical', async () => {
    const user = userEvent.setup()
    const { onChange } = renderBar()
    await user.selectOptions(screen.getByLabelText('Duplicates'), 'canonical')
    expect(onChange).toHaveBeenCalledWith({ duplicates: 'canonical' })
  })

  it('accepts a valid language code', async () => {
    const user = userEvent.setup()
    const { onChange } = renderBar()
    await user.type(screen.getByLabelText('Language'), 'en')
    expect(onChange).toHaveBeenCalledWith({ language: 'e' })
    expect(onChange).toHaveBeenCalledWith({ language: 'en' })
  })

  it('blocks invalid language input and shows a hint', async () => {
    const user = userEvent.setup()
    const { onChange } = renderBar()
    await user.type(screen.getByLabelText('Language'), 'e1')
    expect(onChange).not.toHaveBeenCalledWith({ language: 'e1' })
    expect(screen.getByText(/2–3 letter code/)).toBeInTheDocument()
  })

  it('disables all controls while disabled', () => {
    render(<FilterBar filters={DEFAULT_FILTERS} disabled onChange={vi.fn()} />)
    expect(screen.getByRole('checkbox', { name: 'news' })).toBeDisabled()
    expect(screen.getByLabelText('Time')).toBeDisabled()
    expect(screen.getByLabelText('Language')).toBeDisabled()
  })

  it('offers a clear action when filters are active', async () => {
    const user = userEvent.setup()
    const { onChange } = renderBar({ time: '7d', sourceTypes: ['news'] })
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(onChange).toHaveBeenCalledWith({
      sourceTypes: [],
      time: 'all',
      duplicates: 'all',
      language: '',
    })
  })

  it('hides the clear action when no filters are active', () => {
    renderBar()
    expect(
      screen.queryByRole('button', { name: 'Clear filters' }),
    ).not.toBeInTheDocument()
  })
})
