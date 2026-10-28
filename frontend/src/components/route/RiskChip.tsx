import Chip from '@mui/material/Chip'
import Tooltip from '@mui/material/Tooltip'

import type { RiskLevel } from '@/api/types'
import { riskStyle } from '@/theme/risk'

export interface RiskChipProps {
  level: RiskLevel
  size?: 'small' | 'medium'
  /** Extra context, shown on hover and to screen readers. */
  title?: string | undefined
}

/**
 * Risk level as a coloured chip.
 *
 * `UNKNOWN` is rendered as an outline rather than a solid fill, so a forecast
 * gap is visually distinct from a measured all-clear. Colour alone never
 * carries the meaning — the label is always present, which also keeps this
 * readable for colour-blind users.
 */
export function RiskChip({ level, size = 'small', title }: RiskChipProps) {
  const style = riskStyle(level)
  const isUnknown = level === 'UNKNOWN'

  const chip = (
    <Chip
      size={size}
      label={style.label}
      aria-label={title ? `${style.description}. ${title}` : style.description}
      sx={{
        backgroundColor: isUnknown ? 'transparent' : style.color,
        color: isUnknown ? style.color : style.contrastText,
        border: isUnknown ? `1px dashed ${style.color}` : 'none',
        fontWeight: 700,
        minWidth: 72,
      }}
    />
  )

  return title ? <Tooltip title={title}>{chip}</Tooltip> : chip
}
