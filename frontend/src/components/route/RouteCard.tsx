import BlockIcon from '@mui/icons-material/Block'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import StarIcon from '@mui/icons-material/Star'
import Card from '@mui/material/Card'
import CardActionArea from '@mui/material/CardActionArea'
import Chip from '@mui/material/Chip'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'

import type { AnalysedRoute } from '@/api/types'
import { averageRisk, duration, miles, percent } from '@/lib/format'
import { PALETTE } from '@/theme/theme'

export interface RouteCardProps {
  route: AnalysedRoute
  isSelected: boolean
  onSelect: (routeId: string) => void
}

interface MetricProps {
  label: string
  value: string
  color?: string | undefined
  hint?: string | undefined
}

function Metric({ label, value, color, hint }: MetricProps) {
  const content = (
    <div className="flex min-w-0 flex-col">
      <span
        className="truncate text-sm font-semibold tabular-nums"
        style={color ? { color } : undefined}
      >
        {value}
      </span>
      <span className="truncate text-[0.6875rem] text-muted">{label}</span>
    </div>
  )
  return hint ? <Tooltip title={hint}>{content}</Tooltip> : content
}

/**
 * One route alternative.
 *
 * Every number comes from the backend. The card never decides whether a route
 * is safe — it renders `eligible`, `blocked` and `ineligibility_reasons` as
 * the server reported them.
 */
export function RouteCard({ route, isSelected, onSelect }: RouteCardProps) {
  const { metrics, summary } = route
  const blocked = metrics.blocked || !route.eligible

  const accent = route.is_recommended
    ? PALETTE.success
    : blocked
      ? PALETTE.noTravel
      : PALETTE.primary

  return (
    <Card
      sx={{
        borderColor: isSelected ? accent : PALETTE.border,
        borderLeft: `3px solid ${accent}`,
        backgroundColor: isSelected ? PALETTE.elevated : PALETTE.panel,
        transition: 'border-color 150ms, background-color 150ms',
      }}
    >
      <CardActionArea
        onClick={() => onSelect(route.route_id)}
        aria-pressed={isSelected}
        aria-label={`${route.label}, rank ${route.rank}${
          route.is_recommended ? ', recommended' : ''
        }${blocked ? ', not recommendable' : ''}`}
        className="!p-3"
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Typography variant="h3" className="truncate">
              {route.label}
            </Typography>
            {route.is_recommended && (
              <Chip
                size="small"
                icon={<StarIcon sx={{ fontSize: 14 }} />}
                label="Recommended"
                sx={{
                  backgroundColor: PALETTE.success,
                  color: '#06240F',
                  fontWeight: 700,
                }}
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
          <ChevronRightIcon
            sx={{ color: PALETTE.textSecondary, flexShrink: 0 }}
          />
        </div>

        <div className="mt-3 grid grid-cols-3 gap-3">
          <Metric label="Distance" value={miles(metrics.distance_miles)} />
          <Metric label="Drive time" value={duration(metrics.duration_seconds)} />
          <Metric
            label="Coverage"
            value={percent(metrics.coverage_pct)}
            color={metrics.coverage_pct < 100 ? PALETTE.warning : undefined}
            hint={
              metrics.coverage_pct < 100
                ? `${metrics.unknown_miles.toFixed(1)} mi have no forecast and are excluded from the risk average.`
                : 'Every mile has a forecast.'
            }
          />
        </div>

        <div className="mt-3 grid grid-cols-3 gap-3">
          <Metric
            label="Severe"
            value={miles(metrics.severe_miles, 0)}
            color={metrics.severe_miles > 0 ? PALETTE.severe : undefined}
            hint="Ranking criterion 1: fewest Severe miles."
          />
          <Metric
            label="High"
            value={miles(metrics.high_miles, 0)}
            color={metrics.high_miles > 0 ? PALETTE.high : undefined}
            hint="Ranking criterion 2: fewest High miles."
          />
          <Metric
            label="Avg risk"
            value={averageRisk(metrics.average_risk)}
            hint="Ranking criterion 3: distance-weighted average risk."
          />
        </div>

        {metrics.no_travel_miles > 0 && (
          <Typography
            variant="caption"
            component="p"
            className="mt-2"
            sx={{ color: PALETTE.noTravel }}
          >
            {miles(metrics.no_travel_miles, 1)} under No Travel conditions
          </Typography>
        )}

        {blocked && route.ineligibility_reasons.length > 0 && (
          <ul className="m-0 mt-2 list-none p-0">
            {route.ineligibility_reasons.map((reason) => (
              <li
                key={reason}
                className="text-[0.6875rem] leading-snug text-muted"
              >
                • {reason}
              </li>
            ))}
          </ul>
        )}

        <Typography
          variant="caption"
          component="p"
          className="mt-2 truncate"
          title={summary.arrival_at_local ?? summary.arrival_at}
        >
          Arrives {new Date(summary.arrival_at).toLocaleString(undefined, {
            weekday: 'short',
            hour: 'numeric',
            minute: '2-digit',
          })}
        </Typography>
      </CardActionArea>
    </Card>
  )
}
