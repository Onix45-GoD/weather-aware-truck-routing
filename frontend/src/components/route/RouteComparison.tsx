import BlockIcon from '@mui/icons-material/Block'
import StarIcon from '@mui/icons-material/Star'
import Paper from '@mui/material/Paper'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'

import type { AnalysedRoute, RouteAnalysisResponse } from '@/api/types'
import {
  criterionColumn,
  criterionLabel,
  type ComparisonColumn,
} from '@/features/routes/ranking'
import { averageRisk, duration, miles, percent } from '@/lib/format'
import { PALETTE } from '@/theme/theme'

export interface RouteComparisonProps {
  analysis: RouteAnalysisResponse
  selectedRouteId: string | null
  onSelect: (routeId: string) => void
}

const COLUMNS: Array<{ key: ComparisonColumn; label: string; hint: string }> = [
  { key: 'severe', label: 'Severe mi', hint: 'Criterion 1 — fewest Severe miles' },
  { key: 'high', label: 'High mi', hint: 'Criterion 2 — fewest High miles' },
  { key: 'average', label: 'Avg risk', hint: 'Criterion 3 — lowest distance-weighted average risk (0–4)' },
  { key: 'duration', label: 'Drive time', hint: 'Criterion 4 — shortest travel time' },
  { key: 'coverage', label: 'Coverage', hint: 'Share of miles with a forecast; ties break on fewest unforecast miles' },
  { key: 'status', label: 'Status', hint: 'A No Travel condition or coverage below 95% makes a route ineligible' },
]

/**
 * Every route on one line, in rank order, with the cell that decided each
 * position outlined.
 *
 * The outline comes from the backend's `separated_from_previous_by` -- the
 * table does not compare numbers to find it. Read top to bottom it shows
 * the assessment's rule in action: Severe → High → average risk → time.
 */
export function RouteComparison({ analysis, selectedRouteId, onSelect }: RouteComparisonProps) {
  const routes = [...analysis.routes].sort((a, b) => a.rank - b.rank)

  return (
    <Paper className="flex flex-col overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-hairline px-4 py-3">
        <Typography variant="h2">Route comparison</Typography>
        <Typography variant="caption">
          Ranked by Severe mi → High mi → avg risk → drive time. Outlined cell
          = what decided that row.
        </Typography>
      </div>
      <div className="overflow-x-auto">
        <Table size="small" aria-label="Route comparison">
          <TableHead>
            <TableRow>
              <TableCell>#</TableCell>
              <TableCell>Route</TableCell>
              {COLUMNS.map((column) => (
                <TableCell key={column.key} align={column.key === 'status' ? 'left' : 'right'}>
                  <Tooltip title={column.hint} placement="top">
                    <span className="cursor-help underline decoration-dotted underline-offset-2">
                      {column.label}
                    </span>
                  </Tooltip>
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {routes.map((route, position) => (
              <ComparisonRow
                key={route.route_id}
                route={route}
                previous={position > 0 ? (routes[position - 1] ?? null) : null}
                selected={route.route_id === selectedRouteId}
                onSelect={onSelect}
              />
            ))}
          </TableBody>
        </Table>
      </div>
    </Paper>
  )
}

function ComparisonRow({
  route,
  previous,
  selected,
  onSelect,
}: {
  route: AnalysedRoute
  previous: AnalysedRoute | null
  selected: boolean
  onSelect: (routeId: string) => void
}) {
  const { metrics } = route
  const blocked = !route.eligible
  const deciding = previous ? criterionColumn(route.separated_from_previous_by) : null
  const decidingText = previous
    ? `decided vs #${previous.rank}: ${criterionLabel(route.separated_from_previous_by)}`
    : ''

  const cellProps = (column: ComparisonColumn) =>
    deciding === column
      ? {
          'data-deciding': 'true',
          title: decidingText,
          sx: {
            outline: `2px solid ${PALETTE.primary}`,
            outlineOffset: -2,
            borderRadius: '6px',
            fontWeight: 700,
          },
        }
      : {}

  return (
    <TableRow
      hover
      selected={selected}
      aria-current={selected ? 'true' : undefined}
      role="button"
      tabIndex={0}
      aria-label={`${route.label}, rank ${route.rank}${route.is_recommended ? ', recommended' : ''}${blocked ? ', not usable' : ''}`}
      onClick={() => onSelect(route.route_id)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onSelect(route.route_id)
        }
      }}
      sx={{ cursor: 'pointer', '&.Mui-selected': { backgroundColor: PALETTE.elevated } }}
    >
      <TableCell>{route.rank}</TableCell>
      <TableCell>
        <span className="font-semibold">{route.label}</span>
        {route.is_recommended && (
          <StarIcon
            aria-label="recommended"
            sx={{ fontSize: 14, ml: 0.5, color: PALETTE.success, verticalAlign: 'text-bottom' }}
          />
        )}
      </TableCell>
      <TableCell align="right" {...cellProps('severe')}>
        <span style={metrics.severe_miles > 0 ? { color: PALETTE.severe } : undefined}>
          {miles(metrics.severe_miles, 0)}
        </span>
      </TableCell>
      <TableCell align="right" {...cellProps('high')}>
        <span style={metrics.high_miles > 0 ? { color: PALETTE.high } : undefined}>
          {miles(metrics.high_miles, 0)}
        </span>
      </TableCell>
      <TableCell align="right" {...cellProps('average')}>
        {averageRisk(metrics.average_risk)}
      </TableCell>
      <TableCell align="right" {...cellProps('duration')}>
        {duration(metrics.duration_seconds)}
      </TableCell>
      <TableCell align="right" {...cellProps('coverage')}>
        <span style={metrics.coverage_pct < 100 ? { color: PALETTE.warning } : undefined}>
          {percent(metrics.coverage_pct)}
        </span>
      </TableCell>
      <TableCell {...cellProps('status')}>
        {blocked ? (
          <span className="inline-flex items-center gap-1" style={{ color: PALETTE.noTravel }}>
            <BlockIcon sx={{ fontSize: 14 }} /> Not usable
          </span>
        ) : route.is_recommended ? (
          <span style={{ color: PALETTE.success }}>Recommended</span>
        ) : (
          <span className="text-muted">Eligible</span>
        )}
      </TableCell>
    </TableRow>
  )
}
