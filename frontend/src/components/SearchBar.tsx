import { useEffect, useState, type FormEvent } from 'react'

type SearchBarProps = {
  disabled: boolean
  /** Submit-button label; defaults to Searching…/Search based on `disabled`. */
  label?: string
  /** M23: externally-controlled query text (synced from topic clicks). */
  value?: string
  onValueChange?: (value: string) => void
  onSearch: (query: string) => void
}

export function SearchBar({ disabled, label, value, onValueChange, onSearch }: SearchBarProps) {
  const [internal, setInternal] = useState(value ?? '')
  const [validationError, setValidationError] = useState<string | null>(null)

  useEffect(() => {
    if (value !== undefined) {
      setInternal(value)
    }
  }, [value])

  const current = value !== undefined ? value : internal

  const handleChange = (raw: string) => {
    setInternal(raw)
    onValueChange?.(raw)
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const query = current.trim()
    if (!query) {
      setValidationError('Enter a query to search.')
      return
    }
    setValidationError(null)
    onSearch(query)
  }

  const buttonLabel = label ?? (disabled ? 'Searching…' : 'Search')

  return (
    <form onSubmit={handleSubmit} noValidate>
      <label htmlFor="search-input">Search topic</label>
      <div className="search-row">
        <input
          id="search-input"
          type="text"
          value={current}
          onChange={(event) => handleChange(event.target.value)}
          disabled={disabled}
          placeholder="e.g. artificial intelligence"
          aria-describedby={validationError ? 'search-error' : undefined}
        />
        <button type="submit" disabled={disabled}>
          {buttonLabel}
        </button>
      </div>
      {validationError && (
        <p id="search-error" className="validation-error" role="alert">
          {validationError}
        </p>
      )}
    </form>
  )
}