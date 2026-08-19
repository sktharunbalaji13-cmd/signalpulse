import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { makeResult } from '../test/factories'
import { ResultCard } from './ResultCard'

describe('ResultCard', () => {
  it('renders the full attribution contract', () => {
    render(<ResultCard result={makeResult()} />)

    expect(screen.getByText('REFERENCE')).toBeInTheDocument()
    expect(screen.getByText('Wikipedia')).toBeInTheDocument()

    const link = screen.getByRole('link', { name: 'Artificial intelligence' })
    expect(link).toHaveAttribute('href', 'https://en.wikipedia.org/wiki/Artificial_intelligence')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')

    expect(screen.getByText('Some description text.')).toBeInTheDocument()
    expect(screen.getByText(/Published: Not provided by source/)).toBeInTheDocument()
    expect(screen.getByText(/Retrieved:/)).toBeInTheDocument()
  })

  it('shows the published time when the source provides one', () => {
    render(<ResultCard result={makeResult({ published_at: '2026-08-19T10:00:00Z' })} />)

    const published = screen.getByText(/Published:/).textContent
    expect(published).not.toContain('Not provided by source')
  })
})