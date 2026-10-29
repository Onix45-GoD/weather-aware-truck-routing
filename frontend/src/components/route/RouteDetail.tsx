import BlockIcon from '@mui/icons-material/Block'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ReportProblemIcon from '@mui/icons-material/ReportProblem'
import StarIcon from '@mui/icons-material/Star'
import Alert from '@mui/material/Alert'
import Chip from '@mui/material/Chip'
import Paper from '@mui/material/Paper'
import Typography from '@mui/material/Typography'

import type { AnalysedRoute, RouteAnalysisResponse } from '@/api/types'
import { RiskChip } from '@/components/route/RiskChip'
import {
  explainPosition,
  riskMileSegments,
  worstCheckpoints,
} from '@/features/routes/ranking'
import { dateTime, miles, zoneAbbreviation } from '@/lib/format'
import { riskStyle } from '@/theme/risk'
import { PALETTE } from '@/theme/theme'

export interface RouteDetailProps {
  analysis: RouteAnalysisResponse
  route: AnalysedRoute | null
  timeZone?: string | null | undefined
  /** Jump to a checkpoint (map popup, table row, hourly panel). */
  onSelectCheckpoint?: ((index: number) => void) | undefined
}

/**
 * The selected route in depth: where it ranks and *why*, miles by risk
 * level, the drive window, and the checkpoints that threaten it most. The
 * headline numbers live in the KPI strip under the header.
 *
 * Every number and every reason comes from the backend. The "why" sentence
 * is built from the criterion the ranking engine recorded, never from a
 * second comparison here.
 */
export function RouteDetail({ analysis, route, timeZone, onSelectCheckpoint }: RouteDetailProps) {
  if (!route) {
    return (
      <Paper className="p-4">
        <Typography variant="body2" color="text.secondary">
          Select a route in the comparison table or on the map.
        </Typography>
      </Paper>
    )
  }

  const { metrics, summary } = route
  const ranked = [...analysis.routes].sort((a, b) => a.rank - b.rank)
  const previous = ranked.find((item) => item.rank === route.rank - 1) ?? null
  const why = explainPosition(route, previous, analysis)
  const blocked = !route.eligible
  const segments = riskMileSegments(metrics)
  const worst = worstCheckpoints(route)
  const zone = zoneAbbreviation(summary.arrival_at, timeZone)

  return (
    <Paper className="flex flex-col gap-4 p-4" aria-label={`Route detail: ${route.label}`}>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Typography variant="h2">{route.label}</Typography>
        <Chip size="small" label={`Rank ${route.rank} of ${analysis.routes.length}`} variant="outlined" />
        {route.is_recommended && (
          <Chip
            size="small"
            icon={<StarIcon sx={{ fontSize: 14 }} />}
            label="Recommended"
            sx={{ backgroundColor: PALETTE.success, color: '#06240F', fontWeight: 700 }}
          />
        )}
        {blocked && (
          <Chip
            size="small"
            icon={<BlockIcon sx={{ fontSize: 14 }} />}
            label="Not usable"
            sx={{
              backgroundColor: 'transparent',
              color: PALETTE.noTravel,
              border: `1px dashed ${PALETTE.noTravel}`,
              fontWeight: 700,
            }}
          />
        )}
      </div>

      <Alert
        icon={
          route.is_recommended ? (
            <CheckCircleIcon fontSize="inherit" />
          ) : (
            <ReportProblemIcon fontSize="inherit" />
          )
        }
        severity={route.is_recommended ? 'success' : blocked ? 'warning' : 'info'}
        variant="outlined"
        data-testid="route-why"
      >
        {why}
        {analysis.recommended_route_id === null && route.rank === 1 && (
          <>
            {' '}
            <strong>No route can be recommended.</strong> {analysis.recommendation_reason}
          </>
        )}
      </Alert>

      <div>
        <Typography variant="caption" component="p" className="mb-1">
          Miles by risk level
        </Typography>
        <div
          className="flex h-3 w-full overflow-hidden rounded-full"
          role="img"
          aria-label={segments
            .map((segment) => `${riskStyle(segment.level).label} ${miles(segment.miles, 0)}`)
            .join(', ')}
          style={{ backgroundColor: PALETTE.elevated }}
        >
          {segments.map((segment) => (
            <div
              key={segment.level}
              style={{
                width: `${segment.share * 100}%`,
                backgroundColor: riskStyle(segment.level).color,
                backgroundImage:
                  segment.level === 'UNKNOWN'
                    ? `repeating-linear-gradient(45deg, transparent 0 3px, rgba(0,0,0,0.35) 3px 6px)`
                    : undefined,
              }}
              title={`${riskStyle(segment.level).label}: ${miles(segment.miles, 1)}`}
            />
          ))}
        </div>
        <ul className="m-0 mt-1 flex list-none flex-wrap gap-x-3 gap-y-0.5 p-0 text-[0.6875rem] text-muted">
          {segments.map((segment) => (
            <li key={segment.level} className="flex items-center gap-1">
              <span
                aria-hidden
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: riskStyle(segment.level).color }}
              />
              {riskStyle(segment.level).label} {miles(segment.miles, 0)}
            </li>
          ))}
        </ul>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div>
          <Typography variant="caption" component="p" className="mb-1">
            Drive window
          </Typography>
          <Typography variant="body2">
            Departs {dateTime(summary.departure_at, timeZone)} · arrives{' '}
            {dateTime(summary.arrival_at, timeZone)}
            {zone ? ` ${zone}` : ''}
          </Typography>
          <Typography variant="caption" component="p">
            {route.checkpoints.length} checkpoints
            {summary.eta_source === 'distance_proportional' && ' · ETAs assume a constant average speed'}
          </Typography>
        </div>

        <div>
          <Typography variant="caption" component="p" className="mb-1">
            Worst checkpoints
          </Typography>
          {worst.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              None above Low.
            </Typography>
          ) : (
            <ul className="m-0 flex list-none flex-col gap-1 p-0" aria-label="Worst checkpoints">
              {worst.map((point) => (
                <li key={point.index}>
                  <button
                    type="button"
                    onClick={() => onSelectCheckpoint?.(point.index)}
                    className="flex w-full cursor-pointer items-center justify-between gap-2 rounded-md border border-hairline px-2 py-1 text-left text-xs"
                    style={{ backgroundColor: PALETTE.elevated, color: PALETTE.textPrimary }}
                  >
                    <span>
                      Checkpoint {point.index} · mile {point.distance_from_origin_miles.toFixed(0)} ·{' '}
                      {dateTime(point.eta, timeZone)}
                      {point.risk.driver ? ` · ${point.risk.driver}` : ''}
                    </span>
                    <RiskChip level={point.risk.level} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {blocked && route.ineligibility_reasons.length > 0 && (
        <ul className="m-0 list-none p-0" aria-label="Why this route cannot be recommended">
          {route.ineligibility_reasons.map((reason) => (
            <li key={reason} className="text-xs" style={{ color: PALETTE.noTravel }}>
              • {reason}
            </li>
          ))}
        </ul>
      )}
    </Paper>
  )
}
