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

  it('renders a news result with source attribution and published time', () => {
    render(
      <ResultCard
        result={makeResult({
          source_type: 'news',
          source_name: 'The Guardian',
          title: 'EU passes landmark AI Act',
          url: 'https://www.theguardian.com/technology/2024/jan/15/artificial-intelligence-act-eu',
          author: 'Elena Morris',
          published_at: '2024-01-15T10:30:00Z',
          language: 'en',
        })}
      />,
    )

    expect(screen.getByText('NEWS')).toBeInTheDocument()
    expect(screen.getByText('The Guardian')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'EU passes landmark AI Act' })
    expect(link).toHaveAttribute(
      'href',
      'https://www.theguardian.com/technology/2024/jan/15/artificial-intelligence-act-eu',
    )
    expect(screen.getByText(/Published:/)).not.toHaveTextContent('Not provided by source')
  })

  it('renders a social result with a social chip and attribution', () => {
    render(
      <ResultCard
        result={makeResult({
          source_type: 'social',
          source_name: 'Reddit',
          title: 'Why transformers changed machine learning',
          url: 'https://www.reddit.com/r/artificial/comments/1abcd/why_transformers_changed_machine_learning/',
          author: 'ml_enthusiast',
          published_at: '2026-08-19T10:00:00Z',
        })}
      />,
    )

    expect(screen.getByText('SOCIAL')).toBeInTheDocument()
    expect(screen.getByText('Reddit')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Why transformers changed machine learning' })
    expect(link).toHaveAttribute(
      'href',
      'https://www.reddit.com/r/artificial/comments/1abcd/why_transformers_changed_machine_learning/',
    )
    expect(screen.getByText(/Published:/)).not.toHaveTextContent('Not provided by source')
  })
})