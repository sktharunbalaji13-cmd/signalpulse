import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
})

// M23: some jsdom/vitest environments expose a non-functional `localStorage`.
// SignalPulse's M19.1 history feature is localStorage-backed and must be
// testable end-to-end; provide a minimal in-memory Storage (no dependency).
if (typeof window.localStorage !== 'object' || typeof window.localStorage.getItem !== 'function') {
  const store = new Map<string, string>()
  const storage: Storage = {
    get length() {
      return store.size
    },
    clear: () => store.clear(),
    getItem: (key) => (store.has(String(key)) ? store.get(String(key))! : null),
    key: (index) => Array.from(store.keys())[index] ?? null,
    removeItem: (key) => {
      store.delete(String(key))
    },
    setItem: (key, value) => {
      store.set(String(key), String(value))
    },
  }
  Object.defineProperty(window, 'localStorage', { value: storage, configurable: true })
}