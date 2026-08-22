import { useState, type FormEvent } from 'react'

type SearchBarProps = {
  disabled: boolean
  /** Submit-button label; defaults to Searching…/Search based on `disabled`. */
  label?: string
  onSearch: (query: string) => void
}

export function SearchBar({ disabled, label, onSearch }: SearchBarProps) {
  const [value, setValue] = useState('')
  const [validationError, setValidationError] = useState<string | null>(null)

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const query = value.trim()
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
          value={value}
          onChange={(event) => setValue(event.target.value)}
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
