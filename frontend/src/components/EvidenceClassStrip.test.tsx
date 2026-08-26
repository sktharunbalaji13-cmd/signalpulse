import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

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
})