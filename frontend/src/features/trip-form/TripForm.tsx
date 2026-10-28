import { PlaceholderPanel } from '@/components/PlaceholderPanel'
import { CHECKPOINT_INTERVALS } from '@/types/risk'

/**
 * Trip inputs: origin, destination, departure date/time, load weight and
 * checkpoint interval. Wired to `POST /api/v1/analyze` in Milestone 4.
 */
export function TripForm() {
  return (
    <PlaceholderPanel title="Trip" milestone={4}>
      <p>
        Origin, destination, departure time, cargo weight and checkpoint
        interval ({CHECKPOINT_INTERVALS.join(' / ')} miles).
      </p>
    </PlaceholderPanel>
  )
}
