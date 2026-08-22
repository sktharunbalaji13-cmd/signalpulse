import { useEffect, useState } from 'react'

import type { Filters } from '../hooks/useSearch'

type FilterBarProps = {
  filters: Filters
  disabled?: boolean
  onChange: (next: Partial<Filters>) => void
}

const SOURCE_TYPES = ['news', 'social', 'reference'] as const
const TIME_OPTIONS = ['24h', '7d', '30d', 'all'] as const
const DUPLICATE_OPTIONS = ['all', 'canonical'] as const
const LANGUAGE_RE = /^[a-z]{0,3}$/

export function FilterBar({ filters, disabled = false, onChange }: FilterBarProps) {
  const [languageDraft, setLanguageDraft] = useState(filters.language)

  useEffect(() => {
    setLanguageDraft(filters.language)
  }, [filters.language])

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

  return (
    <fieldset className="filter-bar" disabled={disabled}>
      <legend>Filters</legend>
      <div className="filter-bar__controls">
        <fieldset className="filter-group">
          <legend>Source type</legend>
          {SOURCE_TYPES.map((sourceType) => (
            <label key={sourceType} className="filter-check">
              <input
                type="checkbox"
                checked={filters.sourceTypes.includes(sourceType)}
                onChange={() => toggleSourceType(sourceType)}
              />
              {sourceType}
            </label>
          ))}
        </fieldset>

        <label className="filter-field">
          Time
          <select
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
            value={languageDraft}
            placeholder="e.g. en"
            maxLength={3}
            spellCheck={false}
            onChange={(event) => handleLanguage(event.target.value)}
          />
        </label>
      </div>
      {showLanguageHint && (
        <p className="filter-hint">Language must be a 2–3 letter code like en.</p>
      )}
    </fieldset>
  )
}
