import type { AnalysedRoute, RouteAnalysisResponse } from '@/api/types'
import { averageRisk, duration, miles, percent } from '@/lib/format'
import { PALETTE } from '@/theme/theme'

export interface KpiStripProps {
  analysis: RouteAnalysisResponse
  route: AnalysedRoute | null
}

/**
 * The numbers that matter, in one line under the header: how many routes,
 * which one is recommended, and the selected route's headline metrics.
 */
export function KpiStrip({ analysis, route }: KpiStripProps) {
  const recommended = analysis.routes.find((item) => item.is_recommended) ?? null
  const metrics = route?.metrics ?? null

  return (
    <div
      className="flex flex-wrap items-stretch gap-x-6 gap-y-2 border-b border-hairline bg-panel px-4 py-2"
      aria-label="Trip summary"
      data-testid="kpi-strip"
    >
      <Kpi label="Routes" value={String(analysis.routes.length)} />
      <Kpi
        label="Recommended"
        value={recommended ? recommended.label : 'None'}
        color={recommended ? PALETTE.success : PALETTE.warning}
      />
      {route && metrics && (
        <>
          <Kpi label="Selected" value={route.label} color={PALETTE.primary} />
          <Kpi label="Total distance" value={miles(metrics.distance_miles)} />
          <Kpi label="Driving time" value={duration(metrics.duration_seconds)} />
          <Kpi
            label="Severe"
            value={miles(metrics.severe_miles, 0)}
            color={metrics.severe_miles > 0 ? PALETTE.severe : undefined}
          />
          <Kpi
            label="High"
            value={miles(metrics.high_miles, 0)}
            color={metrics.high_miles > 0 ? PALETTE.high : undefined}
          />
          <Kpi label="Avg risk" value={averageRisk(metrics.average_risk)} />
          <Kpi
            label="Coverage"
            value={percent(metrics.coverage_pct)}
            color={metrics.coverage_pct < 100 ? PALETTE.warning : undefined}
          />
        </>
      )}
    </div>
  )
}

function Kpi({ label, value, color }: { label: string; value: string; color?: string | undefined }) {
  return (
    <div className="flex min-w-0 flex-col">
      <span className="text-[0.625rem] uppercase tracking-wider text-muted">{label}</span>
      <span
        className="truncate text-sm font-semibold tabular-nums"
        style={color ? { color } : undefined}
      >
        {value}
      </span>
    </div>
  )
}
