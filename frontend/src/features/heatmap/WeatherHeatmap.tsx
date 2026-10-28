import { PlaceholderPanel } from '@/components/PlaceholderPanel'

/**
 * Weather heatmap along the trip corridor, with a 0-48 hour forecast slider.
 * All hourly frames are fetched once and held client-side so scrubbing the
 * slider never triggers a network request.
 */
export function WeatherHeatmap() {
  return (
    <PlaceholderPanel title="Corridor forecast" milestone={6}>
      <p>Weather heatmap along the corridor with a 0-48 hour slider.</p>
    </PlaceholderPanel>
  )
}
