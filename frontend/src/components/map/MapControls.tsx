import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'

import { BASEMAP_ORDER, BASEMAPS, type BasemapId } from './basemaps'

export interface MapControlsProps {
  basemap: BasemapId
  onBasemapChange: (id: BasemapId) => void
}

const groupSx = {
  '& .MuiToggleButton-root': {
    px: 1.25,
    py: 0.25,
    fontSize: '0.75rem',
    lineHeight: 1.6,
    textTransform: 'none',
    border: 'none',
  },
} as const

/** Basemap switch, floating over the map. */
export function MapControls({ basemap, onBasemapChange }: MapControlsProps) {
  return (
    <div className="pointer-events-auto absolute right-3 top-3 z-10 rounded-lg border border-hairline bg-panel/90 p-0.5 backdrop-blur-sm">
      <ToggleButtonGroup
        exclusive
        size="small"
        aria-label="Basemap"
        value={basemap}
        onChange={(_event, value: BasemapId | null) => {
          // Exclusive groups report null when the active button is clicked
          // again; a basemap cannot be "none", so that click is a no-op.
          if (value) onBasemapChange(value)
        }}
        sx={groupSx}
      >
        {BASEMAP_ORDER.map((id) => (
          <ToggleButton key={id} value={id} aria-label={BASEMAPS[id].label}>
            {BASEMAPS[id].label}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
    </div>
  )
}
