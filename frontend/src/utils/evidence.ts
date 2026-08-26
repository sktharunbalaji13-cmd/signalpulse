import type { SourceStatus } from '../api/client'

/**
 * M23: SignalPulse evidence-class model (7 classes — there is no
 * "tech-discussion" class; Hacker News belongs to `news`).
 *
 * This is the frontend's single source of truth for class metadata and the
 * source→class mapping. It mirrors the backend adapters' `source_type`
 * values (verified against `app/services/filters.py` VALID_SOURCE_TYPES).
 */

export type EvidenceClassId =
  | 'news'
  | 'social'
  | 'reference'
  | 'research'
  | 'code'
  | 'qa'
  | 'video'

export type EvidenceClass = {
  id: EvidenceClassId
  label: string
}

export const EVIDENCE_CLASSES: EvidenceClass[] = [
  { id: 'news', label: 'News' },
  { id: 'research', label: 'Research' },
  { id: 'code', label: 'Code' },
  { id: 'qa', label: 'Q&A' },
  { id: 'reference', label: 'Reference' },
  { id: 'video', label: 'Video' },
  { id: 'social', label: 'Social' },
]

const SOURCE_CLASS: Record<string, EvidenceClassId> = {
  Wikipedia: 'reference',
  'The Guardian': 'news',
  'Hacker News': 'news',
  arXiv: 'research',
  GitHub: 'code',
  'Stack Overflow': 'qa',
  YouTube: 'video',
  Bluesky: 'social',
  Reddit: 'social',
}

export function classForSource(sourceName: string): EvidenceClassId | undefined {
  return SOURCE_CLASS[sourceName]
}

export type ClassStatus = 'active' | 'dormant' | 'unavailable' | 'absent'

export type ClassAggregate = {
  id: EvidenceClassId
  label: string
  status: ClassStatus
  count: number
  sources: string[]
}

function statusFor(sources: SourceStatus[]): ClassStatus {
  if (sources.length === 0) {
    return 'absent'
  }
  if (sources.some((s) => s.status === 'success')) {
    return 'active'
  }
  if (sources.every((s) => s.status === 'disabled')) {
    return 'dormant'
  }
  return 'unavailable'
}

/** Group a search's per-source outcomes into evidence-class aggregates. */
export function classifySources(sources: SourceStatus[]): ClassAggregate[] {
  const byClass = new Map<EvidenceClassId, SourceStatus[]>()
  for (const source of sources) {
    const classId = classForSource(source.name)
    if (!classId) {
      continue
    }
    const list = byClass.get(classId)
    if (list) {
      list.push(source)
    } else {
      byClass.set(classId, [source])
    }
  }

  return EVIDENCE_CLASSES.map(({ id, label }) => {
    const members = byClass.get(id) ?? []
    const count = members
      .filter((s) => s.status === 'success')
      .reduce((sum, s) => sum + (s.result_count ?? 0), 0)
    return {
      id,
      label,
      status: statusFor(members),
      count,
      sources: members.map((s) => s.name),
    }
  })
}

/** Classes whose sources genuinely failed/timed-out/rate-limited (not disabled). */
export function impactedClasses(sources: SourceStatus[]): ClassAggregate[] {
  return classifySources(sources).filter(
    (aggregate) => aggregate.status === 'unavailable',
  )
}

/** Number of classes with at least one successful source. */
export function activeClassCount(sources: SourceStatus[]): number {
  return classifySources(sources).filter((aggregate) => aggregate.status === 'active')
    .length
}