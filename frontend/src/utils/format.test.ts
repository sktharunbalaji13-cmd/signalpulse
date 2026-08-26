import { describe, expect, it } from 'vitest'

import { formatDate, formatRelativeTime, formatTimestamp } from './format'

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

describe('formatRelativeTime (M23 FE-C)', () => {
  const now = Date.parse('2026-08-25T12:00:00Z')

  it('says just now under a minute', () => {
    expect(formatRelativeTime('2026-08-25T11:59:30Z', now)).toBe('just now')
  })

  it('formats minutes', () => {
    expect(formatRelativeTime('2026-08-25T11:55:00Z', now)).toBe('5m ago')
  })

  it('formats hours', () => {
    expect(formatRelativeTime('2026-08-25T10:00:00Z', now)).toBe('2h ago')
  })

  it('formats days', () => {
    expect(formatRelativeTime('2026-08-22T12:00:00Z', now)).toBe('3d ago')
  })

  it('falls back to a date beyond five weeks', () => {
    expect(formatRelativeTime('2024-01-15T10:00:00Z', now)).toContain('2024')
  })

  it('handles invalid input', () => {
    expect(formatRelativeTime('not-a-date', now)).toBe('time unknown')
  })
})
