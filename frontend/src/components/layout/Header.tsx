import HelpOutlineIcon from '@mui/icons-material/HelpOutlined'
import TuneIcon from '@mui/icons-material/Tune'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import { useState } from 'react'

import type { RouteAnalysisResponse } from '@/api/types'

export interface HeaderProps {
  analysis: RouteAnalysisResponse | null
  /** Opens the trip drawer. Only rendered below `lg`. */
  onOpenTripForm: () => void
  /** Opens the "How to read this" guide. */
  onOpenHelp: () => void
}

export function Header({ analysis, onOpenTripForm, onOpenHelp }: HeaderProps) {
  // The logo is a static asset; if it is missing the title stands alone
  // rather than showing a broken image.
  const [logoFailed, setLogoFailed] = useState(false)

  return (
    <header className="flex items-center justify-between gap-3 border-b border-hairline bg-panel px-4 py-2.5">
      <div className="flex min-w-0 items-center gap-3">
        {!logoFailed && (
          <img
            src="/logo.png"
            alt=""
            width={32}
            height={32}
            className="h-8 w-8 shrink-0 object-contain"
            onError={() => setLogoFailed(true)}
          />
        )}
        <div className="min-w-0">
          <Typography variant="h1" className="truncate">
            Weather-Aware Truck Routing
          </Typography>
          {analysis && (
            <Typography variant="caption" component="p" className="truncate">
              {analysis.origin.label} → {analysis.destination.label}
            </Typography>
          )}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <Tooltip title="How to read this dashboard">
          <IconButton size="small" aria-label="How to read this dashboard" onClick={onOpenHelp}>
            <HelpOutlineIcon />
          </IconButton>
        </Tooltip>

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
