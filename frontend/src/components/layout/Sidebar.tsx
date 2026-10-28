import AltRouteIcon from '@mui/icons-material/AltRoute'
import InsightsIcon from '@mui/icons-material/Insights'
import LocalShippingIcon from '@mui/icons-material/LocalShipping'
import RuleIcon from '@mui/icons-material/Rule'
import Tooltip from '@mui/material/Tooltip'
import type { ReactNode } from 'react'

import { PALETTE } from '@/theme/theme'

export type SectionId = 'plan' | 'results' | 'methodology'

interface NavItem {
  id: SectionId
  label: string
  icon: ReactNode
}

const ITEMS: NavItem[] = [
  { id: 'plan', label: 'Plan route', icon: <AltRouteIcon /> },
  { id: 'results', label: 'Analysis results', icon: <InsightsIcon /> },
  { id: 'methodology', label: 'Risk methodology', icon: <RuleIcon /> },
]

export interface SidebarProps {
  active: SectionId
  onSelect: (id: SectionId) => void
}

/**
 * Icon-only rail, visible from `lg` upward.
 *
 * Below that the same destinations appear in the mobile bottom bar — the rail
 * is hidden rather than shrunk, because a 64 px column of icons is wasted
 * width on a phone.
 */
export function Sidebar({ active, onSelect }: SidebarProps) {
  return (
    <nav
      aria-label="Main"
      className="hidden w-[68px] shrink-0 flex-col items-center gap-2 border-r border-hairline bg-panel py-4 lg:flex"
    >
      <div
        className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl"
        style={{ backgroundColor: PALETTE.primary }}
        aria-hidden
      >
        <LocalShippingIcon sx={{ color: '#F8FAFC', fontSize: 22 }} />
      </div>

      {ITEMS.map((item) => {
        const isActive = item.id === active
        return (
          <Tooltip key={item.id} title={item.label} placement="right">
            <button
              type="button"
              onClick={() => onSelect(item.id)}
              aria-current={isActive ? 'page' : undefined}
              aria-label={item.label}
              className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-xl border-0 transition-colors"
              style={{
                backgroundColor: isActive ? PALETTE.primary : 'transparent',
                color: isActive ? '#F8FAFC' : PALETTE.textSecondary,
              }}
            >
              {item.icon}
            </button>
          </Tooltip>
        )
      })}
    </nav>
  )
}

export { ITEMS as NAV_ITEMS }
