import { useEffect, useState } from 'react'

import { api, ApiError, type AdminStatsResponse, type AdminWindow } from '../api/client'

const WINDOWS: AdminWindow[] = ['24h', '7d', '30d']

type ViewState = 'loading' | 'login' | 'ready' | 'error'

export function AdminDashboard() {
  const [view, setView] = useState<ViewState>('loading')
  const [stats, setStats] = useState<AdminStatsResponse | null>(null)
  const [window, setWindow] = useState<AdminWindow>('7d')
  const [loginKey, setLoginKey] = useState('')
  const [loginError, setLoginError] = useState<string | null>(null)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  async function loadStats(w: AdminWindow): Promise<boolean> {
    try {
      const data = await api.getAdminStats(w)
      setStats(data)
      setFetchError(null)
      return true
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setView('login')
      } else {
        setFetchError('Could not load admin statistics. Please try again.')
        // Show the error surface even when nothing has loaded yet.
        if (!stats) setView('ready')
      }
      return false
    }
  }

  useEffect(() => {
    void loadStats('7d').then((ok) => {
      if (ok) setView('ready')
    })
  }, [])

  async function handleLogin(event: React.FormEvent) {
    event.preventDefault()
    setLoginError(null)
    if (!loginKey) {
      setLoginError('Enter the admin key.')
      return
    }
    try {
      await api.adminLogin(loginKey)
      setLoginKey('') // never retained in state beyond the request
      const ok = await loadStats(window)
      if (ok) setView('ready')
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setLoginError('Invalid admin key.')
      } else {
        setLoginError('Login failed. Please try again.')
      }
    }
  }

  async function handleLogout() {
    try {
      await api.adminLogout()
    } finally {
      setStats(null)
      setView('login')
    }
  }

  function switchWindow(w: AdminWindow) {
    setWindow(w)
    void loadStats(w)
  }

  async function refresh() {
    setRefreshing(true)
    await loadStats(window)
    setRefreshing(false)
  }

  if (view === 'loading') {
    return <div className="admin admin--loading">Loading admin workspace…</div>
  }

  if (view === 'login') {
    return (
      <div className="admin admin--login">
        <div className="panel admin-login">
          <p className="eyebrow">Admin Workspace</p>
          <h2 className="admin-login__title">SignalPulse Operations</h2>
          <form onSubmit={handleLogin}>
            <label htmlFor="admin-key">Admin key</label>
            <input
              id="admin-key"
              type="password"
              autoComplete="current-password"
              value={loginKey}
              onChange={(e) => setLoginKey(e.target.value)}
              placeholder="Enter admin key"
            />
            {loginError && (
              <p className="validation-error" role="alert">
                {loginError}
              </p>
            )}
            <button type="submit">Sign in</button>
          </form>
          <p className="admin-login__hint">
            The key is exchanged once for a short-lived session; it is never stored in the browser.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="admin">
      <div className="admin-head">
        <div>
          <p className="eyebrow">Admin Workspace</p>
          <h2 className="admin-head__title">SignalPulse Operations</h2>
        </div>
        <div className="admin-head__actions">
          <div className="admin-windows" role="group" aria-label="Time window">
            {WINDOWS.map((w) => (
              <button
                key={w}
                type="button"
                className={`window-btn ${w === window ? 'window-btn--active' : ''}`}
                aria-pressed={w === window}
                onClick={() => switchWindow(w)}
              >
                {w}
              </button>
            ))}
          </div>
          <button type="button" onClick={() => void refresh()} disabled={refreshing}>
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
          <button type="button" className="admin-logout" onClick={() => void handleLogout()}>
            Sign out
          </button>
        </div>
      </div>

      {fetchError && (
        <div className="notice notice--error">
          <p>{fetchError}</p>
        </div>
      )}

      {stats && (
        <>
          <section className="admin-section" aria-label="Overview">
            <p className="eyebrow">Overview</p>
            <div className="admin-cards">
              <div className="admin-card">
                <span className="admin-card__label">Searches</span>
                <span className="admin-card__value">{stats.searches.total}</span>
              </div>
              <div className="admin-card">
                <span className="admin-card__label">Status mix</span>
                <div className="admin-card__bars">
                  {Object.entries(stats.searches.by_status).map(([status, count]) => (
                    <div key={status} className="bar-row">
                      <span className="bar-row__label">{status}</span>
                      <div className="bar-track">
                        <div
                          className="bar-fill"
                          style={{
                            width: `${stats.searches.total ? (count / stats.searches.total) * 100 : 0}%`,
                          }}
                        />
                      </div>
                      <span className="bar-row__value">{count}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="admin-card">
                <span className="admin-card__label">Latency p50 / p95 / p99</span>
                <span className="admin-card__value admin-card__value--mono">
                  {stats.latency_ms.p50 ?? '—'} / {stats.latency_ms.p95 ?? '—'} /{' '}
                  {stats.latency_ms.p99 ?? '—'}
                  <small> ms</small>
                </span>
              </div>
              <div className="admin-card">
                <span className="admin-card__label">Empty-result queries</span>
                <span className="admin-card__value">{stats.queries.empty_result_count}</span>
              </div>
            </div>
          </section>

          <section className="admin-section" aria-label="Source health">
            <p className="eyebrow">Source Health</p>
            <div className="panel">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Success</th>
                    <th>Failed</th>
                    <th>Disabled</th>
                    <th>Avg latency</th>
                    <th>Avg yield</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(stats.sources).map(([name, s]) => (
                    <tr key={name}>
                      <td>{name}</td>
                      <td className="admin-table__ok">{s.success ?? 0}</td>
                      <td className={s.failed ? 'admin-table__err' : ''}>{s.failed ?? 0}</td>
                      <td className="admin-table__muted">{s.disabled ?? 0}</td>
                      <td>{s.avg_latency_ms ? `${Math.round(s.avg_latency_ms)} ms` : '—'}</td>
                      <td>{s.avg_results ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <div className="admin-grid">
            <section className="admin-section" aria-label="Deduplication">
              <p className="eyebrow">Deduplication</p>
              <div className="admin-cards">
                <div className="admin-card">
                  <span className="admin-card__label">Duplicate groups</span>
                  <span className="admin-card__value">{stats.dedup.total_groups}</span>
                </div>
                <div className="admin-card">
                  <span className="admin-card__label">Duplicates removed</span>
                  <span className="admin-card__value">{stats.dedup.duplicates_removed}</span>
                </div>
              </div>
            </section>

            <section className="admin-section" aria-label="Semantic stage">
              <p className="eyebrow">Semantic Stage</p>
              <div className="panel">
                <p className="semantic-badge">
                  {stats.semantic.disabled ? 'EXPERIMENTAL — DORMANT' : 'ACTIVE'}{' '}
                  <span className="semantic-badge__detail">
                    (SEM1 local ONNX; disabled by default on free-tier)
                  </span>
                </p>
                <div className="admin-card__rows">
                  <span className="admin-card__label">Runs with stage</span>
                  <span>{stats.semantic.searches_with_stage ?? 0}</span>
                  <span className="admin-card__label">Avg inference</span>
                  <span>{stats.semantic.avg_ms ? `${stats.semantic.avg_ms} ms` : '—'}</span>
                </div>
              </div>
            </section>

            <section className="admin-section" aria-label="Retention">
              <p className="eyebrow">Retention</p>
              <div className="panel">
                <div className="admin-card__rows">
                  <span className="admin-card__label">Retention period</span>
                  <span>{stats.retention.days} days</span>
                  <span className="admin-card__label">Clock</span>
                  <span className="mono">{stats.retention.clock}</span>
                </div>
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  )
}