import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ReportProblemIcon from '@mui/icons-material/ReportProblem'
import Alert from '@mui/material/Alert'
import Paper from '@mui/material/Paper'
import Typography from '@mui/material/Typography'

import type { AnalysedRoute, RouteAnalysisResponse } from '@/api/types'
import { averageRisk, duration, miles, percent } from '@/lib/format'
import { PALETTE } from '@/theme/theme'

interface StatProps {
  value: string
  label: string
  color?: string | undefined
}

function Stat({ value, label, color }: StatProps) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span
        className="text-xl font-semibold tabular-nums leading-none"
        style={color ? { color } : undefined}
      >
        {value}
      </span>
      <span className="text-xs text-muted">{label}</span>
    </div>
  )
}

export interface RouteSummaryProps {
  analysis: RouteAnalysisResponse
  route: AnalysedRoute | null
}

/**
 * Headline metrics for the selected route, plus the recommendation verdict.
 *
 * The verdict text is the backend's `recommendation_reason` verbatim — it
 * already names the ranking criterion that decided the outcome, and
 * paraphrasing it here would risk saying something the engine did not.
 */
export function RouteSummary({ analysis, route }: RouteSummaryProps) {
  const hasRecommendation = analysis.recommended_route_id !== null

  if (!route) {
    return (
      <Paper className="p-4">
        <Typography variant="body2" color="text.secondary">
          Select a route to see its summary.
        </Typography>
      </Paper>
    )
  }

  const { metrics } = route

  return (
    <Paper className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Typography variant="h2">Route summary</Typography>
        <Typography variant="caption">{route.label}</Typography>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
        <Stat value={miles(metrics.distance_miles)} label="Total distance" />
        <Stat value={duration(metrics.duration_seconds)} label="Driving time" />
        <Stat
          value={miles(metrics.severe_miles, 0)}
          label="Severe weather"
          color={metrics.severe_miles > 0 ? PALETTE.severe : undefined}
        />
        <Stat
          value={miles(metrics.high_miles, 0)}
          label="High risk"
          color={metrics.high_miles > 0 ? PALETTE.high : undefined}
        />
        <Stat value={averageRisk(metrics.average_risk)} label="Average risk" />
        <Stat
          value={percent(metrics.coverage_pct)}
          label="Weather coverage"
          color={metrics.coverage_pct < 100 ? PALETTE.warning : PALETTE.success}
        />
      </div>

      {hasRecommendation ? (
        <Alert
          icon={<CheckCircleIcon fontSize="inherit" />}
          severity="success"
          variant="outlined"
        >
          {analysis.recommendation_reason}
        </Alert>
      ) : (
        <Alert
          icon={<ReportProblemIcon fontSize="inherit" />}
          severity="warning"
          variant="outlined"
        >
          <strong>No route can be recommended. </strong>
          {analysis.recommendation_reason}
        </Alert>
      )}

      <Typography variant="caption" component="p">
        Times are estimated driving time only. Driver hours-of-service, fuel
        stops and live traffic are not modelled.
        {route.summary.eta_source === 'distance_proportional' &&
          ' This route had no per-segment timings from the provider, so ETAs assume a constant average speed.'}
      </Typography>
    </Paper>
  )
}
