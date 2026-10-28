import type {
  CheckpointWeatherResponse,
  CurrentConditions,
  ForecastSlot,
} from '@/api/types'

const BASE = Date.UTC(2026, 10, 2, 12)

export function makeForecastSlot(
  index: number,
  overrides: Partial<ForecastSlot> = {},
): ForecastSlot {
  return {
    at: new Date(BASE + index * 3 * 3_600_000).toISOString(),
    condition: 'Clear',
    description: 'clear sky',
    icon: '01d',
    temp_f: 60 + index,
    feels_like_f: 58 + index,
    precipitation_probability: index / 10,
    wind_mph: 5 + index,
    wind_gust_mph: null,
    wind_deg: 180,
    humidity_pct: 50,
    cloud_pct: 10 * index,
    rain_in_3h: null,
    snow_in_3h: null,
    ...overrides,
  }
}

export function makeCurrentConditions(
  overrides: Partial<CurrentConditions> = {},
): CurrentConditions {
  return {
    observed_at: new Date(BASE).toISOString(),
    condition: 'Clouds',
    description: 'few clouds',
    icon: '02d',
    temp_f: 71.6,
    feels_like_f: 73.4,
    wind_mph: 2.2,
    wind_gust_mph: 4.5,
    wind_deg: 112,
    humidity_pct: 94,
    pressure_hpa: 1021,
    visibility_miles: 6.2,
    cloud_pct: 20,
    rain_in_last_hour: 0.1,
    snow_in_last_hour: null,
    sunrise: null,
    sunset: null,
    ...overrides,
  }
}

/** A response whose ETA slot is index 3 (NOW + 9h), a rainy one. */
export function makeCheckpointWeather(
  overrides: Partial<CheckpointWeatherResponse> = {},
): CheckpointWeatherResponse {
  const forecast = Array.from({ length: 8 }, (_, i) =>
    i === 3
      ? makeForecastSlot(i, {
          condition: 'Rain',
          description: 'light rain',
          icon: '10d',
          rain_in_3h: 0.2,
        })
      : makeForecastSlot(i),
  )
  return {
    source: 'openweathermap',
    coordinate: { latitude: 39.74, longitude: -104.99 },
    place_name: 'Denver',
    current: makeCurrentConditions(),
    forecast,
    eta: new Date(BASE + 9 * 3_600_000 - 50 * 60_000).toISOString(),
    at_eta: forecast[3] ?? null,
    eta_gap_minutes: 50,
    eta_beyond_horizon: false,
    forecast_horizon_end: forecast[7]?.at ?? null,
    ...overrides,
  }
}
