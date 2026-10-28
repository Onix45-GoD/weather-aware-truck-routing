import Alert from '@mui/material/Alert'
import AlertTitle from '@mui/material/AlertTitle'
import Drawer from '@mui/material/Drawer'
import LinearProgress from '@mui/material/LinearProgress'
import Paper from '@mui/material/Paper'
import Typography from '@mui/material/Typography'
import { useCallback, useMemo, useState } from 'react'

import type { RouteAnalysisRequest } from '@/api/types'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Header } from '@/components/layout/Header'
import { Sidebar, type SectionId } from '@/components/layout/Sidebar'
import { LazyRouteMap } from '@/components/map/LazyRouteMap'
import { RouteCard } from '@/components/route/RouteCard'
import { RouteSummary } from '@/components/route/RouteSummary'
import { CheckpointDetails } from '@/components/weather/CheckpointDetails'
import { CheckpointTable } from '@/components/weather/CheckpointTable'
import { WeatherProfile } from '@/components/weather/WeatherProfile'
import { useHealth } from '@/features/health/useHealth'
import { TripForm } from '@/features/route-analysis/TripForm'
import { useRouteAnalysis } from '@/features/route-analysis/useRouteAnalysis'

export default function App() {
  const { data, error, fieldErrors, isLoading, status, analyse } =
    useRouteAnalysis()
  const { weatherOverlaysAvailable } = useHealth()

  const [section, setSection] = useState<SectionId>('plan')
  const [tripOpen, setTripOpen] = useState(false)
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<number | null>(
    null,
  )

  // Selection follows each new analysis: the recommended route if there is
  // one, otherwise the top-ranked, so the dashboard is never blank.
  //
  // Adjusted during render rather than in an effect (the pattern React
  // documents for "state derived from props"). An effect would render once
  // with the stale selection, then immediately re-render — a visible flash
  // of the previous route's checkpoints.
  const [lastAnalysis, setLastAnalysis] = useState(data)
  if (data !== lastAnalysis) {
    setLastAnalysis(data)
    setSelectedRouteId(
      data ? (data.recommended_route_id ?? data.routes[0]?.route_id ?? null) : null,
    )
    setSelectedCheckpoint(null)
  }

  const selectedRoute = useMemo(
    () =>
      data?.routes.find((route) => route.route_id === selectedRouteId) ?? null,
    [data, selectedRouteId],
  )

  const checkpoint = useMemo(() => {
    if (!selectedRoute || selectedCheckpoint === null) return null
    return (
      selectedRoute.checkpoints.find(
        (point) => point.index === selectedCheckpoint,
      ) ?? null
    )
  }, [selectedRoute, selectedCheckpoint])

  const timeZone = data?.request.departure_timezone ?? null

  const handleSubmit = useCallback(
    (payload: RouteAnalysisRequest) => {
      setTripOpen(false)
      void analyse(payload)
    },
    [analyse],
  )

  const handleSelectRoute = useCallback((routeId: string) => {
    setSelectedRouteId(routeId)
    setSelectedCheckpoint(null)
  }, [])

  const tripForm = (
    <TripForm
      onSubmit={handleSubmit}
      isLoading={isLoading}
      fieldErrors={fieldErrors}
    />
  )

  // Warnings that are not tied to one route — coverage, DST, shortfalls.
  const globalWarnings = data?.warnings.filter((w) => !w.route_id) ?? []

  return (
    <div className="flex h-full min-h-0 w-full">
      <Sidebar active={section} onSelect={setSection} />

      <div className="flex min-w-0 flex-1 flex-col">
        <Header analysis={data} onOpenTripForm={() => setTripOpen(true)} />
        {isLoading && <LinearProgress />}

        <main className="scroll-area flex-1 p-3">
          {/* 1440px: form | map | alternatives. Collapses to one column on
              smaller screens rather than shrinking all three. */}
          <div className="grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)_320px]">
            <aside className="hidden min-w-0 lg:block">
              <Paper className="p-4">
                <Typography variant="h2" className="mb-4">
                  Trip details
                </Typography>
                {tripForm}
              </Paper>
            </aside>

            <section className="flex min-w-0 flex-col gap-3">
              {error && (
                <Alert
                  severity={error.isValidation ? 'warning' : 'error'}
                  variant="outlined"
                >
                  <AlertTitle>
                    {error.isValidation
                      ? 'Check the trip details'
                      : 'Analysis failed'}
                  </AlertTitle>
                  {error.message}
                  {error.isRetryable && ' You can try again.'}
                </Alert>
              )}

              {globalWarnings.map((warning) => (
                <Alert
                  key={`${warning.code}-${warning.message}`}
                  severity={
                    warning.code === 'NO_ELIGIBLE_ROUTE' ||
                    warning.code === 'WEATHER_UNAVAILABLE'
                      ? 'warning'
                      : 'info'
                  }
                  variant="outlined"
                >
                  {warning.message}
                </Alert>
              ))}

              {/* The map needs a real height; a percentage of an auto-height
                  grid child would collapse to zero. */}
              {/* The boundary is what stops a MapLibre crash from unmounting
                  the whole dashboard. If the map dies, it dies alone: the
                  route cards, checkpoints and weather stay on screen. */}
              <div className="h-[clamp(320px,48vh,560px)] min-w-0">
                <ErrorBoundary label="The map">
                  <LazyRouteMap
                    routes={data?.routes ?? []}
                    selectedRouteId={selectedRouteId}
                    selectedCheckpointIndex={selectedCheckpoint}
                    onSelectRoute={handleSelectRoute}
                    onSelectCheckpoint={setSelectedCheckpoint}
                    origin={data?.origin ?? null}
                    destination={data?.destination ?? null}
                    weatherOverlaysAvailable={weatherOverlaysAvailable}
                  />
                </ErrorBoundary>
              </div>

              {data && <RouteSummary analysis={data} route={selectedRoute} />}
            </section>

            <aside
              aria-label="Route alternatives"
              className="flex min-w-0 flex-col gap-3"
            >
              <Typography variant="h2">
                Route alternatives
                {data ? ` (${data.routes.length})` : ''}
              </Typography>

              {!data && status !== 'loading' && (
                <Paper className="p-4">
                  <Typography variant="body2" color="text.secondary">
                    Enter a trip and select <strong>Analyze Routes</strong> to
                    compare up to three options by weather risk.
                  </Typography>
                </Paper>
              )}

              {data?.routes.map((route) => (
                <RouteCard
                  key={route.route_id}
                  route={route}
                  isSelected={route.route_id === selectedRouteId}
                  onSelect={handleSelectRoute}
                />
              ))}
            </aside>
          </div>

          {data && selectedRoute && (
            <div className="mt-3 grid min-w-0 grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <div className="flex min-w-0 flex-col gap-3">
                <CheckpointTable
                  route={selectedRoute}
                  selectedIndex={selectedCheckpoint}
                  onSelect={setSelectedCheckpoint}
                  timeZone={timeZone}
                />
              </div>
              <div className="flex min-w-0 flex-col gap-3">
                <CheckpointDetails
                  route={selectedRoute}
                  checkpoint={checkpoint}
                  timeZone={timeZone}
                />
                <WeatherProfile
                  route={selectedRoute}
                  selectedIndex={selectedCheckpoint}
                  onSelect={setSelectedCheckpoint}
                />
              </div>
            </div>
          )}
        </main>
      </div>

      {/* Below `lg` the trip form lives in a drawer rather than stealing
          width from the map. */}
      <Drawer
        anchor="left"
        open={tripOpen}
        onClose={() => setTripOpen(false)}
        slotProps={{ paper: { sx: { width: 320, p: 2 } } }}
      >
        <Typography variant="h2" className="mb-4">
          Trip details
        </Typography>
        {tripForm}
      </Drawer>
    </div>
  )
}
