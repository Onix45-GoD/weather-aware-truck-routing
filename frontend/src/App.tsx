import { WeatherHeatmap } from '@/features/heatmap/WeatherHeatmap'
import { RouteMap } from '@/features/map/RouteMap'
import { RoutesPanel } from '@/features/routes-panel/RoutesPanel'
import { TripForm } from '@/features/trip-form/TripForm'

/**
 * Application shell.
 *
 * The layout is final -- inputs and route comparison in a left rail, map and
 * corridor forecast filling the main area -- but every region is a placeholder
 * until its milestone lands.
 */
export default function App() {
  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">Weather-Aware Truck Routing</h1>
        <p className="app__subtitle">
          Choose the safest route from weather, load weight and travel time.
        </p>
      </header>

      <main className="app__main">
        <div className="app__rail">
          <TripForm />
          <RoutesPanel />
        </div>
        <div className="app__content">
          <RouteMap />
          <WeatherHeatmap />
        </div>
      </main>
    </div>
  )
}
