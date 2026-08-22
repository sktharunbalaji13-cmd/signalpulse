import { describe, expect, it } from 'vitest'

import { formatDate, formatTimestamp } from './format'

describe('formatTimestamp', () => {
  it('explains a missing timestamp', () => {
    expect(formatTimestamp(null)).toBe('Not provided by source')
  })

  it('formats an ISO timestamp', () => {
    const formatted = formatTimestamp('2026-08-19T12:00:00Z')
    expect(formatted).toContain('2026')
  })
})

describe('formatDate', () => {
  it('formats an ISO date', () => {
    expect(formatDate('2026-08-19T12:00:00Z')).toContain('2026')
  })
})
