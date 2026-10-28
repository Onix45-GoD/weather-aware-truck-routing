import Paper from '@mui/material/Paper'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import Typography from '@mui/material/Typography'

import type { AnalysedRoute } from '@/api/types'
import { clockTime, measurement, zoneAbbreviation } from '@/lib/format'
import { RiskChip } from '@/components/route/RiskChip'
import { PALETTE } from '@/theme/theme'

export interface CheckpointTableProps {
  route: AnalysedRoute
  selectedIndex: number | null
  onSelect: (index: number) => void
  timeZone?: string | null | undefined
}

/**
 * Every checkpoint on the selected route.
 *
 * Missing measurements render as an em dash, never `0` — zero would claim
 * calm, dry conditions we did not observe.
 *
 * On narrow screens the wind/rain/snow columns are hidden rather than
 * squeezed; the risk chip and ETA are what matter at a glance, and the
 * detail panel carries the rest.
 */
export function CheckpointTable({
  route,
  selectedIndex,
  onSelect,
  timeZone,
}: CheckpointTableProps) {
  const zone = route.checkpoints[0]
    ? zoneAbbreviation(route.checkpoints[0].eta, timeZone)
    : ''

  return (
    <Paper className="flex min-h-0 flex-col overflow-hidden">
      <div className="flex items-baseline justify-between gap-2 border-b border-hairline px-4 py-3">
        <Typography variant="h2">Checkpoints</Typography>
        <Typography variant="caption">
          {route.checkpoints.length} on {route.label}
        </Typography>
      </div>

      <div className="scroll-area max-h-[22rem]">
        <Table size="small" stickyHeader aria-label="Route checkpoints">
          <TableHead>
            <TableRow>
              <TableCell>#</TableCell>
              <TableCell align="right">Mile</TableCell>
              <TableCell>ETA{zone ? ` (${zone})` : ''}</TableCell>
              <TableCell align="right" className="hidden sm:table-cell">
                Wind
              </TableCell>
              <TableCell align="right" className="hidden md:table-cell">
                Rain
              </TableCell>
              <TableCell align="right" className="hidden md:table-cell">
                Snow
              </TableCell>
              <TableCell>Risk</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {route.checkpoints.map((checkpoint) => {
              const isSelected = checkpoint.index === selectedIndex
              return (
                <TableRow
                  key={`${route.route_id}-${checkpoint.index}`}
                  hover
                  selected={isSelected}
                  onClick={() => onSelect(checkpoint.index)}
                  tabIndex={0}
                  role="button"
                  aria-label={`Checkpoint ${checkpoint.index} at mile ${checkpoint.distance_from_origin_miles.toFixed(0)}`}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      onSelect(checkpoint.index)
                    }
                  }}
                  sx={{
                    cursor: 'pointer',
                    '&.Mui-selected': { backgroundColor: PALETTE.elevated },
                  }}
                >
                  <TableCell>{checkpoint.index}</TableCell>
                  <TableCell align="right">
                    {checkpoint.distance_from_origin_miles.toFixed(0)}
                  </TableCell>
                  <TableCell>{clockTime(checkpoint.eta, timeZone)}</TableCell>
                  <TableCell align="right" className="hidden sm:table-cell">
                    {measurement(checkpoint.weather?.wind_mph, 'mph', 0)}
                  </TableCell>
                  <TableCell align="right" className="hidden md:table-cell">
                    {measurement(checkpoint.weather?.rain_in_hr, 'in', 2)}
                  </TableCell>
                  <TableCell align="right" className="hidden md:table-cell">
                    {measurement(checkpoint.weather?.snow_in_hr, 'in', 2)}
                  </TableCell>
                  <TableCell>
                    <RiskChip level={checkpoint.risk.level} />
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </Paper>
  )
}
