import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { SourceStatus } from '../api/client'
import { EvidenceClassStrip } from './EvidenceClassStrip'

function source(name: string, status: SourceStatus['status'], result_count: number | null = null): SourceStatus {
  return { name, status, result_count, latency_ms: null, error_type: null, error: null }
}

describe('EvidenceClassStrip', () => {
  it('renders nothing when there are no sources', () => {
    const { container } = render(<EvidenceClassStrip sources={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows active classes with aggregate counts', () => {
    render(
      <EvidenceClassStrip
        sources={[
          source('Wikipedia', 'success', 10),
          source('The Guardian', 'success', 8),
          source('Hacker News', 'success', 5),
        ]}
      />,
    )
    expect(screen.getByText('News')).toBeInTheDocument()
    expect(screen.getByText('· 13')).toBeInTheDocument()
    expect(screen.getByText('Reference')).toBeInTheDocument()
    expect(screen.getByText('· 10')).toBeInTheDocument()
  })

  it('marks a dormant class explicitly (social with all sources disabled)', () => {
    render(
      <EvidenceClassStrip
        sources={[
          source('Wikipedia', 'success', 10),
          source('Reddit', 'disabled'),
          source('Bluesky', 'disabled'),
        ]}
      />,
    )
    expect(screen.getByText('Social')).toBeInTheDocument()
    expect(screen.getByText('· dormant')).toBeInTheDocument()
  })

  it('marks a genuinely-failing class as unavailable', () => {
    render(
      <EvidenceClassStrip
        sources={[source('YouTube', 'failed'), source('Wikipedia', 'success', 4)]}
      />,
    )
    expect(screen.getByText('Video')).toBeInTheDocument()
    expect(screen.getByText('· unavailable')).toBeInTheDocument()
  })

  it('hides classes with no registered source', () => {
    render(<EvidenceClassStrip sources={[source('Wikipedia', 'success', 4)]} />)
    expect(screen.queryByText('Code')).not.toBeInTheDocument()
    expect(screen.queryByText('Social')).not.toBeInTheDocument()
  })

  it('renders active classes as interactive lens buttons (M23)', async () => {
    const user = userEvent.setup()
    const onToggleClass = vi.fn()
    render(
      <EvidenceClassStrip
        sources={[source('Wikipedia', 'success', 10)]}
        onToggleClass={onToggleClass}
      />,
    )
    const chip = screen.getByRole('button', { name: /Reference/ })
    expect(chip).toHaveAttribute('aria-pressed', 'false')
    await user.click(chip)
    expect(onToggleClass).toHaveBeenCalledWith('reference')
  })

  it('marks a selected lens chip as pressed (M23)', () => {
    render(
      <EvidenceClassStrip
        sources={[source('Wikipedia', 'success', 10)]}
        selected={['reference']}
        onToggleClass={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: /Reference/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('keeps dormant chips informational rather than interactive (M23)', () => {
    render(
      <EvidenceClassStrip
        sources={[source('Reddit', 'disabled'), source('Bluesky', 'disabled')]}
        onToggleClass={vi.fn()}
      />,
    )
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByText('Social')).toBeInTheDocument()
    expect(screen.getByText('· dormant')).toBeInTheDocument()
  })
})