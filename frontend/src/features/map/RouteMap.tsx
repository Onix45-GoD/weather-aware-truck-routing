import { PlaceholderPanel } from '@/components/PlaceholderPanel'

/**
 * Interactive map: every route alternative, its checkpoints coloured by risk
 * level, ETAs and the route summary. MapLibre GL arrives in Milestone 4 --
 * no map library is installed yet.
 */
export function RouteMap() {
  return (
    <PlaceholderPanel title="Map" milestone={4}>
      <p>
        Route geometry, risk-coloured checkpoints, ETAs and route summaries.
      </p>
    </PlaceholderPanel>
  )
}
