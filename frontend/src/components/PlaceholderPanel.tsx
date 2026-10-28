import type { ReactNode } from 'react'

interface PlaceholderPanelProps {
  title: string
  milestone: number
  children: ReactNode
}

/**
 * A labelled region standing in for a feature that is not built yet.
 *
 * Each placeholder names the milestone that will fill it, so the shell is
 * self-documenting rather than a grid of empty boxes. Replaced by the real
 * component as each milestone lands.
 */
export function PlaceholderPanel({
  title,
  milestone,
  children,
}: PlaceholderPanelProps) {
  return (
    <section className="panel" aria-labelledby={`panel-${slug(title)}`}>
      <header className="panel__header">
        <h2 id={`panel-${slug(title)}`} className="panel__title">
          {title}
        </h2>
        <span className="panel__badge">Milestone {milestone}</span>
      </header>
      <div className="panel__body">{children}</div>
    </section>
  )
}

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-')
}
