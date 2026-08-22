import type { ReactNode } from 'react'

type StatusBannerProps = {
  kind: 'info' | 'warning' | 'error'
  children: ReactNode
}

export function StatusBanner({ kind, children }: StatusBannerProps) {
  return (
    <p
      className={`status-banner status-banner--${kind}`}
      role={kind === 'error' ? 'alert' : undefined}
    >
      {children}
    </p>
  )
}
