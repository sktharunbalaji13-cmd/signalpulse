import { describe, expect, it } from 'vitest'

import type { SourceStatus } from '../api/client'
import {
  EVIDENCE_CLASSES,
  activeClassCount,
  classifySources,
  classForSource,
  impactedClasses,
} from './evidence'

function source(name: string, status: SourceStatus['status'], result_count: number | null = null): SourceStatus {
  return { name, status, result_count, latency_ms: null, error_type: null, error: null }
}

describe('evidence class model', () => {
  it('defines exactly the 7 real evidence classes (no tech-discussion)', () => {
    const ids = EVIDENCE_CLASSES.map((c) => c.id).sort()
    expect(ids).toEqual(['code', 'news', 'qa', 'reference', 'research', 'social', 'video'])
  })

  it('maps every known source to its class', () => {
    expect(classForSource('Wikipedia')).toBe('reference')
    expect(classForSource('The Guardian')).toBe('news')
    expect(classForSource('Hacker News')).toBe('news')
    expect(classForSource('arXiv')).toBe('research')
    expect(classForSource('GitHub')).toBe('code')
    expect(classForSource('Stack Overflow')).toBe('qa')
    expect(classForSource('YouTube')).toBe('video')
    expect(classForSource('Bluesky')).toBe('social')
    expect(classForSource('Reddit')).toBe('social')
  })

  it('returns undefined for unknown sources', () => {
    expect(classForSource('Mystery Feed')).toBeUndefined()
  })
})

describe('classifySources', () => {
  it('aggregates success counts per class', () => {
    const result = classifySources([
      source('Wikipedia', 'success', 10),
      source('The Guardian', 'success', 8),
      source('Hacker News', 'success', 5),
      source('Reddit', 'disabled'),
      source('Bluesky', 'disabled'),
    ])
    const news = result.find((c) => c.id === 'news')
    expect(news?.status).toBe('active')
    expect(news?.count).toBe(13)
    const reference = result.find((c) => c.id === 'reference')
    expect(reference?.status).toBe('active')
    expect(reference?.count).toBe(10)
    const social = result.find((c) => c.id === 'social')
    expect(social?.status).toBe('dormant')
    expect(social?.sources).toEqual(['Reddit', 'Bluesky'])
  })

  it('marks a class unavailable when a source genuinely fails', () => {
    const result = classifySources([source('YouTube', 'failed'), source('Wikipedia', 'success', 4)])
    const video = result.find((c) => c.id === 'video')
    expect(video?.status).toBe('unavailable')
  })

  it('marks classes without sources as absent', () => {
    const result = classifySources([source('Wikipedia', 'success', 4)])
    for (const id of ['code', 'qa', 'video', 'social']) {
      expect(result.find((c) => c.id === id)?.status).toBe('absent')
    }
  })
})

describe('impactedClasses / activeClassCount', () => {
  it('reports only genuinely-failing classes', () => {
    const impacted = impactedClasses([
      source('Wikipedia', 'success', 10),
      source('YouTube', 'timeout'),
      source('Reddit', 'disabled'),
    ])
    expect(impacted.map((c) => c.id)).toEqual(['video'])
  })

  it('ignores dormant classes when nothing genuinely failed', () => {
    const impacted = impactedClasses([
      source('Wikipedia', 'success', 10),
      source('Reddit', 'disabled'),
      source('Bluesky', 'disabled'),
    ])
    expect(impacted).toEqual([])
  })

  it('counts active classes', () => {
    expect(
      activeClassCount([
        source('Wikipedia', 'success', 10),
        source('The Guardian', 'success', 8),
        source('Reddit', 'disabled'),
      ]),
    ).toBe(2)
  })
})