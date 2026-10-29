import Typography from '@mui/material/Typography'

import { RISK_ORDER, riskStyle } from '@/theme/risk'

/**
 * How to use and read the dashboard. One source for the first-visit panel
 * and the header's "How to read this" dialog, so the two never drift.
 *
 * Deliberately says what the colours *are* (the backend's classification)
 * without restating a single threshold: the numbers live in one place,
 * the Django domain, and the README's methodology section.
 */
export function GuideContent() {
  return (
    <div className="flex flex-col gap-4">
      <ol className="m-0 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-3">
        <Step n={1} title="Enter the trip">
          Origin, destination, local departure time and zone, cargo weight,
          and how often to sample the weather along the way.
        </Step>
        <Step n={2} title="Analyze">
          Up to three truck routes are fetched, the forecast is read at every
          checkpoint for the time you would actually be there, and each
          stretch is classified.
        </Step>
        <Step n={3} title="Read the result">
          Routes are ranked by fewest Severe miles, then High miles, then
          average risk, then drive time. The comparison table outlines the
          cell that decided each row.
        </Step>
      </ol>

      <div>
        <Typography variant="caption" component="p" className="mb-1">
          Risk colours
        </Typography>
        <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-xs">
          {[...RISK_ORDER, 'UNKNOWN' as const].map((level) => (
            <li key={level} className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: riskStyle(level).color }}
              />
              {riskStyle(level).label}
              {level === 'UNKNOWN' && (
                <span className="text-muted"> — no forecast; never counted as safe</span>
              )}
            </li>
          ))}
        </ul>
      </div>

      <dl className="m-0 grid grid-cols-1 gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
        <Term term="Dots and the dotted line">
          Each checkpoint at the time the truck reaches it. This is what the
          ranking and the recommendation are computed from.
        </Term>
        <Term term="Wide band and halos">
          The whole route at one instant — the hour chosen on the corridor
          timeline. A display view; moving it changes nothing about the trip.
        </Term>
        <Term term="Corridor timeline">
          0–48 h after departure, one frame per hour from the same forecast.
          Hatched hours have no forecast from the provider. Play steps through
          the hours that exist.
        </Term>
        <Term term="Click a checkpoint">
          Opens its weather on the map: conditions at ETA and a 48-hour risk
          strip for that spot. The panel below shows the full hourly table.
        </Term>
      </dl>
    </div>
  )
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span
        aria-hidden
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-elevated text-xs font-bold text-ink"
      >
        {n}
      </span>
      <div>
        <Typography variant="body2" component="p" className="font-semibold">
          {title}
        </Typography>
        <Typography variant="caption" component="p">
          {children}
        </Typography>
      </div>
    </li>
  )
}

function Term({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="font-semibold text-ink">{term}</dt>
      <dd className="m-0 text-muted">{children}</dd>
    </div>
  )
}
