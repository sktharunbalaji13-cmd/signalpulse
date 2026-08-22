import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Pagination } from './Pagination'

describe('Pagination', () => {
  it('renders nothing for a single page', () => {
    render(<Pagination page={1} totalPages={1} onPageChange={vi.fn()} />)
    expect(screen.queryByRole('navigation', { name: 'Result pages' })).not.toBeInTheDocument()
  })

  it('shows the current page out of the total', () => {
    render(<Pagination page={2} totalPages={3} onPageChange={vi.fn()} />)
    expect(screen.getByText('Page 2 of 3')).toBeInTheDocument()
  })

  it('disables previous on the first page', () => {
    render(<Pagination page={1} totalPages={3} onPageChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: /previous/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /next/i })).toBeEnabled()
  })

  it('disables next on the last page', () => {
    render(<Pagination page={3} totalPages={3} onPageChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled()
  })

  it('requests adjacent pages', async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()
    render(<Pagination page={2} totalPages={3} onPageChange={onPageChange} />)
    await user.click(screen.getByRole('button', { name: /previous/i }))
    await user.click(screen.getByRole('button', { name: /next/i }))
    expect(onPageChange).toHaveBeenNthCalledWith(1, 1)
    expect(onPageChange).toHaveBeenNthCalledWith(2, 3)
  })
})
