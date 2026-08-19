import { useState, type FormEvent } from 'react'

type SearchBarProps = {
  disabled: boolean
  onSearch: (query: string) => void
}

export function SearchBar({ disabled, onSearch }: SearchBarProps) {
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
          {disabled ? 'Searching…' : 'Search'}
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