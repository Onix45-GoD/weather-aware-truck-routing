import { PlaceholderPanel } from '@/components/PlaceholderPanel'

/**
 * Side-by-side comparison of the route alternatives: risk-mile breakdown,
 * ETAs, travel time, the recommendation badge and the reason it won.
 */
export function RoutesPanel() {
  return (
    <PlaceholderPanel title="Routes" milestone={5}>
      <p>
        Route comparison, risk-mile breakdown and the recommended option with
        the criterion that decided it.
      </p>
    </PlaceholderPanel>
  )
}
