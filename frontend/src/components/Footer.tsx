const SOCIAL_LINKS = [
  { label: 'Email', value: 'sktharunbalaji13@gmail.com', href: 'mailto:sktharunbalaji13@gmail.com' },
  { label: 'GitHub', value: 'sktharunbalaji13-cmd', href: 'https://github.com/sktharunbalaji13-cmd' },
  {
    label: 'LinkedIn',
    value: 'Tharun Balaji',
    href: 'https://www.linkedin.com/in/tharun-balaji-0ba196327/',
  },
]

export function Footer() {
  return (
    <footer className="footer">
      <div className="footer__inner">
        <div className="footer__brand">
          <span className="footer__mark" aria-hidden="true">
            ▸
          </span>
          <span className="footer__pulse" aria-hidden="true" />
          <span className="footer__name">SIGNALPULSE</span>
        </div>
        <p className="footer__tagline">
          Multi-source intelligence, ranked for signal, not noise.
        </p>
        <nav className="footer__connect" aria-label="Connect">
          <p className="footer__label">Connect</p>
          <ul className="footer__links">
            {SOCIAL_LINKS.map((link) => (
              <li key={link.label}>
                <a href={link.href} target="_blank" rel="noopener noreferrer">
                  <span className="footer__link-label">{link.label}</span>
                  <span className="footer__link-value">{link.value}</span>
                  <span className="footer__link-arrow" aria-hidden="true">
                    ↗
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </div>
      <div className="footer__legal">
        <span>© 2026 SignalPulse</span>
        <span>Built for evidence-driven research.</span>
      </div>
    </footer>
  )
}