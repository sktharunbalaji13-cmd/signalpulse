import { useEffect, useState } from 'react'

import type { SourceStatus } from '../api/client'
import type { Filters } from '../hooks/useSearch'
import { classifySources } from '../utils/evidence'

type FilterBarProps = {
  filters: Filters
  disabled?: boolean
  sources?: SourceStatus[]
  onChange: (next: Partial<Filters>) => void
}

const SOURCE_TYPES = ['news', 'social', 'reference', 'research', 'code', 'qa', 'video'] as const
const TIME_OPTIONS = ['24h', '7d', '30d', 'all'] as const
const DUPLICATE_OPTIONS = ['all', 'canonical'] as const
const LANGUAGE_RE = /^[a-z]{0,3}$/

export function FilterBar({ filters, disabled = false, sources = [], onChange }: FilterBarProps) {
  const [languageDraft, setLanguageDraft] = useState(filters.language)

  useEffect(() => {
    setLanguageDraft(filters.language)
  }, [filters.language])

  // M23 FE-E: annotate dormant classes (all sources disabled) so a filter that
  // can currently return nothing is never a surprise. aria-hidden keeps the
  // annotation out of each checkbox's accessible name.
  const classAggregates = classifySources(sources)
  const dormantClasses = new Set(
    classAggregates
      .filter((aggregate) => aggregate.status === 'dormant')
      .map((aggregate) => aggregate.id),
  )

  function toggleSourceType(sourceType: string) {
    const next = filters.sourceTypes.includes(sourceType)
      ? filters.sourceTypes.filter((t) => t !== sourceType)
      : [...filters.sourceTypes, sourceType]
    onChange({ sourceTypes: next })
  }

  function handleLanguage(raw: string) {
    const value = raw.toLowerCase()
    setLanguageDraft(value)
    if (LANGUAGE_RE.test(value)) {
      onChange({ language: value })
    }
  }

  const showLanguageHint = languageDraft !== '' && !/^[a-z]{2,3}$/.test(languageDraft)
  const filtersActive =
    filters.sourceTypes.length > 0 ||
    filters.time !== 'all' ||
    filters.duplicates === 'canonical' ||
    filters.language !== ''

  return (
    <div className="filter-bar">
      <div className="filter-bar__controls">
        <fieldset className="filter-group" disabled={disabled}>
          <legend>Source Type</legend>
          {SOURCE_TYPES.map((sourceType) => (
            <label key={sourceType} className="filter-check">
              <input
                type="checkbox"
                checked={filters.sourceTypes.includes(sourceType)}
                onChange={() => toggleSourceType(sourceType)}
              />
              {sourceType}
              {dormantClasses.has(sourceType) && (
                <span className="filter-check__note" aria-hidden="true">
                  {' '}· dormant
                </span>
              )}
            </label>
          ))}
        </fieldset>

        <div className="filter-fields">
          <label className="filter-field">
            Time
            <select
              disabled={disabled}
              value={filters.time}
              onChange={(event) => onChange({ time: event.target.value as Filters['time'] })}
            >
              {TIME_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>

          <label className="filter-field">
            Duplicates
            <select
              disabled={disabled}
              value={filters.duplicates}
              onChange={(event) =>
                onChange({ duplicates: event.target.value as Filters['duplicates'] })
              }
            >
              {DUPLICATE_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>

          <label className="filter-field">
            Language
            <input
              type="text"
              disabled={disabled}
              value={languageDraft}
              placeholder="Any"
              maxLength={3}
              spellCheck={false}
              onChange={(event) => handleLanguage(event.target.value)}
            />
          </label>
        </div>

        {filtersActive && (
          <button
            type="button"
            className="filter-clear"
            disabled={disabled}
            onClick={() => onChange({ sourceTypes: [], time: 'all', duplicates: 'all', language: '' })}
          >
            Clear filters
          </button>
        )}
      </div>
      {showLanguageHint && (
        <p className="filter-hint">Language must be a 2–3 letter code like en.</p>
      )}
    </div>
  )
}