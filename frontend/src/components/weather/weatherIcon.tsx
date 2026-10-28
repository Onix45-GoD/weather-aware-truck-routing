import AcUnitIcon from '@mui/icons-material/AcUnit'
import CloudIcon from '@mui/icons-material/Cloud'
import DehazeIcon from '@mui/icons-material/Dehaze'
import GrainIcon from '@mui/icons-material/Grain'
import NightsStayIcon from '@mui/icons-material/NightsStay'
import ThunderstormIcon from '@mui/icons-material/Thunderstorm'
import UmbrellaIcon from '@mui/icons-material/Umbrella'
import WbCloudyIcon from '@mui/icons-material/WbCloudy'
import WbSunnyIcon from '@mui/icons-material/WbSunny'
import type { SvgIconProps } from '@mui/material/SvgIcon'
import type { ComponentType } from 'react'

/**
 * OpenWeatherMap icon codes -> a bundled icon.
 *
 * The codes are documented and stable (`01d` clear day … `50n` mist night).
 * Rendering them with local icons rather than `openweathermap.org/img/...`
 * keeps the browser from calling the provider at all, which is the rule
 * everywhere else in this app, and means the panel works offline from a
 * cached response.
 */
const BY_CODE: Record<string, ComponentType<SvgIconProps>> = {
  '01d': WbSunnyIcon,
  '01n': NightsStayIcon,
  '02d': WbCloudyIcon,
  '02n': WbCloudyIcon,
  '03d': CloudIcon,
  '03n': CloudIcon,
  '04d': CloudIcon,
  '04n': CloudIcon,
  '09d': GrainIcon,
  '09n': GrainIcon,
  '10d': UmbrellaIcon,
  '10n': UmbrellaIcon,
  '11d': ThunderstormIcon,
  '11n': ThunderstormIcon,
  '13d': AcUnitIcon,
  '13n': AcUnitIcon,
  '50d': DehazeIcon,
  '50n': DehazeIcon,
}

const BY_CONDITION: Record<string, ComponentType<SvgIconProps>> = {
  Clear: WbSunnyIcon,
  Clouds: CloudIcon,
  Rain: UmbrellaIcon,
  Drizzle: GrainIcon,
  Thunderstorm: ThunderstormIcon,
  Snow: AcUnitIcon,
}

export interface WeatherIconProps extends SvgIconProps {
  code: string
  /** Fallback when the code is unknown: the provider's `main` word. */
  condition?: string | undefined
}

export function WeatherIcon({ code, condition, ...rest }: WeatherIconProps) {
  const Icon =
    BY_CODE[code] ?? (condition ? BY_CONDITION[condition] : undefined) ?? CloudIcon
  return <Icon {...rest} />
}
