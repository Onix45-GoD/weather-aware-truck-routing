import CssBaseline from '@mui/material/CssBaseline'
import GlobalStyles from '@mui/material/GlobalStyles'
import { StyledEngineProvider, ThemeProvider } from '@mui/material/styles'
import type { ReactNode } from 'react'

import { theme } from '@/theme/theme'

/**
 * Application providers.
 *
 * `enableCssLayer` is the load-bearing prop. Without it MUI injects
 * *unlayered* styles, and unlayered CSS beats every `@layer` in the
 * cascade — so Tailwind utilities would silently lose to MUI defaults no
 * matter how specific they were, and the usual next move is `!important`
 * everywhere. With it, MUI lands in the `mui` layer, which the order declared
 * in `styles/index.css` places below `utilities`.
 *
 * The `GlobalStyles` layer declaration repeats that order. It is redundant
 * when the stylesheet loads first and cheap insurance when bundling or
 * code-splitting reorders things — the first declaration of a layer order is
 * the one that counts, so emitting it twice is harmless.
 */
export function Providers({ children }: { children: ReactNode }) {
  return (
    <StyledEngineProvider enableCssLayer>
      <GlobalStyles styles="@layer theme, base, mui, vendor, components, utilities;" />
      <ThemeProvider theme={theme} defaultMode="dark">
        <CssBaseline enableColorScheme />
        {children}
      </ThemeProvider>
    </StyledEngineProvider>
  )
}
