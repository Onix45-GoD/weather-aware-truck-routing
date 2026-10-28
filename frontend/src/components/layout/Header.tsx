import CloudQueueIcon from '@mui/icons-material/CloudQueue'
import TuneIcon from '@mui/icons-material/Tune'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'

import type { RouteAnalysisResponse } from '@/api/types'
import { PALETTE } from '@/theme/theme'

export interface HeaderProps {
  analysis: RouteAnalysisResponse | null
  /** Opens the trip drawer. Only rendered below `lg`. */
  onOpenTripForm: () => void
}

export function Header({ analysis, onOpenTripForm }: HeaderProps) {
  const providers = analysis?.meta.providers

  return (
    <header className="flex items-center justify-between gap-3 border-b border-hairline bg-panel px-4 py-3">
      <div className="flex min-w-0 items-center gap-3">
        <div className="min-w-0">
          <Typography variant="h1" className="truncate">
            Weather-Aware Truck Routing
          </Typography>
          <Typography variant="caption" component="p" className="truncate">
            {analysis
              ? `${analysis.origin.label} → ${analysis.destination.label}`
              : 'Plan a trip to see weather risk along every route option'}
          </Typography>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {providers && (
          <Tooltip
            title={
              `Routing: ${providers['routing']} · Weather: ${providers['weather']}` +
              (analysis ? ` · analysed in ${Math.round(analysis.meta.elapsed_ms)} ms` : '')
            }
          >
            <Chip
              size="small"
              icon={<CloudQueueIcon sx={{ fontSize: 15 }} />}
              label={providers['weather'] ?? 'providers'}
              sx={{
                backgroundColor: PALETTE.elevated,
                color: PALETTE.textSecondary,
                border: `1px solid ${PALETTE.border}`,
              }}
              className="hidden sm:inline-flex"
            />
          </Tooltip>
        )}

        <Button
          variant="outlined"
          size="small"
          startIcon={<TuneIcon />}
          onClick={onOpenTripForm}
          className="lg:!hidden"
        >
          Trip
        </Button>
      </div>
    </header>
  )
}
