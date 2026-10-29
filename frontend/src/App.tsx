import Alert from '@mui/material/Alert'
import AlertTitle from '@mui/material/AlertTitle'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Drawer from '@mui/material/Drawer'
import LinearProgress from '@mui/material/LinearProgress'
import Paper from '@mui/material/Paper'
import Typography from '@mui/material/Typography'
import { useCallback, useMemo, useState } from 'react'

import type { RiskLevel, RouteAnalysisRequest } from '@/api/types'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Header } from '@/components/layout/Header'
import { CheckpointPopup } from '@/components/map/CheckpointPopup'
import { LazyRouteMap } from '@/components/map/LazyRouteMap'
import { RouteCard } from '@/components/route/RouteCard'
import { RouteComparison } from '@/components/route/RouteComparison'
import { RouteDetail } from '@/components/route/RouteDetail'
import { CheckpointDetails } from '@/components/weather/CheckpointDetails'
import { CheckpointTable } from '@/components/weather/CheckpointTable'
import { ForecastTimeline } from '@/features/corridor/ForecastTimeline'
import { frameLabel } from '@/features/corridor/frameLabel'
import { checkpointSeries } from '@/features/corridor/series'
import { useCorridorForecast } from '@/features/corridor/useCorridorForecast'
import { useForecastPlayback } from '@/features/corridor/useForecastPlayback'
import {
  exampleTrip,
  onboardingDismissed,
  rememberOnboardingDismissed,
} from '@/features/onboarding/exampleTrip'
import { GuideContent } from '@/features/onboarding/GuideContent'
import { OnboardingPanel } from '@/features/onboarding/OnboardingPanel'
import { TripForm, type TripFormValues } from '@/features/route-analysis/TripForm'
import { useRouteAnalysis } from '@/features/route-analysis/useRouteAnalysis'

export default function App() {
  const { data, error, fieldErrors, isLoading, status, analyse } =
    useRouteAnalysis()

  const [tripOpen, setTripOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  // First-visit guide. Hidden for good once dismissed (per browser) and
  // never shown over results; the header's help button reopens the
  // same content as a dialog.
  const [guideDismissed, setGuideDismissed] = useState(onboardingDismissed)
  // Seeds the trip form. A new `key` remounts it with these values, which
  // is how "Try an example trip" fills the form as well as running it.
  const [formSeed, setFormSeed] = useState<{ key: number; values?: TripFormValues }>({ key: 0 })
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<number | null>(
    null,
  )
  // The corridor timeline's hour, 0..48. Display state only (D28): it is
  // never sent with an analysis and never changes the recommendation.
  const [forecastHour, setForecastHour] = useState(0)

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
    setForecastHour(0)
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

  // --- corridor forecast ---------------------------------------------------
  const corridor = useCorridorForecast(data, selectedRoute)
  const frames = corridor.data?.frames ?? null
  const playback = useForecastPlayback(frames, forecastHour, setForecastHour)

  const frame = useMemo(
    () => frames?.find((item) => item.hour === forecastHour) ?? null,
    [frames, forecastHour],
  )

  // Risk per checkpoint for the selected hour, for the map band.
  const corridorLevels = useMemo(() => {
    if (!frame) return null
    const levels = new Map<number, RiskLevel>()
    for (const point of frame.checkpoints) levels.set(point.index, point.risk.level)
    return levels
  }, [frame])

  const corridorLabel = frame
    ? `+${frame.hour} h · ${frameLabel(frame.at, timeZone)}`
    : null

  // The selected checkpoint across all 49 hours -- for the popup and panel.
  const series = useMemo(
    () => checkpointSeries(frames, selectedCheckpoint),
    [frames, selectedCheckpoint],
  )

  const handleSubmit = useCallback(
    (payload: RouteAnalysisRequest) => {
      setTripOpen(false)
      void analyse(payload)
    },
    [analyse],
  )

  const dismissGuide = useCallback(() => {
    rememberOnboardingDismissed()
    setGuideDismissed(true)
  }, [])

  const runExample = useCallback(() => {
    const example = exampleTrip()
    setFormSeed((seed) => ({ key: seed.key + 1, values: example.values }))
    void analyse(example.payload)
  }, [analyse])

  const handleSelectRoute = useCallback((routeId: string) => {
    setSelectedRouteId(routeId)
    setSelectedCheckpoint(null)
  }, [])

  const tripForm = (
    <TripForm
      key={formSeed.key}
      initialValues={formSeed.values}
      onSubmit={handleSubmit}
      isLoading={isLoading}
      fieldErrors={fieldErrors}
    />
  )

  // Offline fixture providers synthesise routes and weather. Say so, loudly:
  // a synthetic forecast must never be mistaken for a real one.
  const fixtureProviders = data
    ? Object.entries(data.meta.providers)
        .filter(([, name]) => name === 'fixtures')
        .map(([role]) => role)
    : []

  // Warnings that are not tied to one route — coverage, DST, shortfalls.
  const globalWarnings = data?.warnings.filter((w) => !w.route_id) ?? []

  const popup = checkpoint
    ? {
        checkpoint,
        content: (
          <CheckpointPopup
            checkpoint={checkpoint}
            timeZone={timeZone}
            series={series}
            hour={forecastHour}
            onHourChange={setForecastHour}
          />
        ),
      }
    : null

  return (
    <div className="flex h-full min-h-0 w-full">
      <a
        href="#results"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-elevated focus:px-3 focus:py-2 focus:text-ink"
      >
        Skip to results
      </a>
      <div className="flex min-w-0 flex-1 flex-col">
        <Header
          analysis={data}
          onOpenTripForm={() => setTripOpen(true)}
          onOpenHelp={() => setHelpOpen(true)}
        />
        {isLoading && <LinearProgress />}

        <main id="results" className="scroll-area flex-1 p-3" tabIndex={-1}>
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
              {!data && !guideDismissed && status !== 'loading' && (
                <OnboardingPanel
                  onExample={runExample}
                  onDismiss={dismissGuide}
                  exampleLoading={isLoading}
                />
              )}

              {fixtureProviders.length > 0 && (
                <Alert severity="warning" variant="filled" data-testid="fixture-banner">
                  <AlertTitle>Offline fixture data</AlertTitle>
                  {fixtureProviders.join(', ')} came from the synthetic fixture
                  provider. These routes and this weather are not real; configure
                  the live providers before relying on anything shown.
                </Alert>
              )}

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
              <div className="h-[clamp(360px,52vh,600px)] min-w-0">
                <ErrorBoundary label="The map">
                  <LazyRouteMap
                    routes={data?.routes ?? []}
                    selectedRouteId={selectedRouteId}
                    selectedCheckpointIndex={selectedCheckpoint}
                    onSelectRoute={handleSelectRoute}
                    onSelectCheckpoint={setSelectedCheckpoint}
                    origin={data?.origin ?? null}
                    destination={data?.destination ?? null}
                    corridorLevels={corridorLevels}
                    corridorLabel={corridorLabel}
                    popup={popup}
                  />
                </ErrorBoundary>
              </div>

              {data && (
                <ForecastTimeline
                  corridor={corridor}
                  hour={forecastHour}
                  onHourChange={setForecastHour}
                  playback={playback}
                  timeZone={timeZone}
                  enabled={Boolean(selectedRoute)}
                />
              )}

              {data && (
                <RouteComparison
                  analysis={data}
                  selectedRouteId={selectedRouteId}
                  onSelect={handleSelectRoute}
                />
              )}

              {data && (
                <RouteDetail
                  analysis={data}
                  route={selectedRoute}
                  timeZone={timeZone}
                  onSelectCheckpoint={setSelectedCheckpoint}
                />
              )}
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
              <CheckpointTable
                route={selectedRoute}
                selectedIndex={selectedCheckpoint}
                onSelect={setSelectedCheckpoint}
                timeZone={timeZone}
              />
              <CheckpointDetails
                route={selectedRoute}
                checkpoint={checkpoint}
                timeZone={timeZone}
                series={series}
                hour={forecastHour}
                onHourChange={setForecastHour}
              />
            </div>
          )}
        </main>
      </div>

      <Dialog open={helpOpen} onClose={() => setHelpOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>How to read this dashboard</DialogTitle>
        <DialogContent dividers>
          <GuideContent />
        </DialogContent>
        <DialogActions>
          {!data && (
            <Button onClick={() => { setHelpOpen(false); runExample() }}>Try an example trip</Button>
          )}
          <Button variant="contained" onClick={() => setHelpOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>

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
