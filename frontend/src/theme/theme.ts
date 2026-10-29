/**
 * MUI theme — the single source of global component appearance.
 *
 * Division of labour with Tailwind, kept strict so the two never fight:
 *
 * - **MUI** owns component *appearance*: colours, radii, typography,
 *   borders, states. Set here in the theme, not scattered through `sx`.
 * - **Tailwind** owns *layout*: grid, flex, spacing, sizing, breakpoints,
 *   overflow.
 *
 * When both could style something, the theme wins and the Tailwind class is
 * dropped. `!important` is never the answer; the cascade layer order declared
 * in `styles/index.css` lets Tailwind utilities override MUI when genuinely
 * needed.
 */

import { createTheme, type ThemeOptions } from '@mui/material/styles'

/**
 * Charcoal ground, brand orange for controls. The risk palette (`risk.ts`)
 * is separate on purpose: orange on a *control* means selected, orange on
 * *data* means High risk, and the two never share a surface -- controls
 * never carry risk colours and risk colours never style chrome.
 */
export const PALETTE = {
  appBackground: '#0B0D10',
  panel: '#15181D',
  elevated: '#1D2127',
  primary: '#FF8A1F',
  /** Logo gradient, for the one primary action. */
  brandGradient: 'linear-gradient(135deg, #FFB300 0%, #FF6A00 100%)',
  success: '#22C55E',
  warning: '#EAB308',
  high: '#F97316',
  severe: '#EF4444',
  noTravel: '#A855F7',
  textPrimary: '#F3F4F6',
  textSecondary: '#9AA3B2',
  border: '#262B33',
} as const

const FONT_STACK = [
  'Inter',
  'system-ui',
  '-apple-system',
  'Segoe UI',
  'Roboto',
  'Helvetica Neue',
  'sans-serif',
].join(', ')

/** Distances, durations and metrics line up when digits are fixed-width. */
const TABULAR = "'tnum' 1, 'cv01' 1"

const options: ThemeOptions = {
  cssVariables: true,
  palette: {
    mode: 'dark',
    background: { default: PALETTE.appBackground, paper: PALETTE.panel },
    primary: { main: PALETTE.primary, contrastText: '#1A0E00' },
    success: { main: PALETTE.success },
    warning: { main: PALETTE.warning },
    error: { main: PALETTE.severe },
    divider: PALETTE.border,
    text: { primary: PALETTE.textPrimary, secondary: PALETTE.textSecondary },
  },
  shape: { borderRadius: 12 },
  spacing: 8,
  typography: {
    fontFamily: FONT_STACK,
    h1: { fontSize: '1.5rem', fontWeight: 650, letterSpacing: '-0.02em' },
    h2: { fontSize: '1.125rem', fontWeight: 650, letterSpacing: '-0.01em' },
    h3: { fontSize: '0.9375rem', fontWeight: 600 },
    body1: { fontSize: '0.875rem' },
    body2: { fontSize: '0.8125rem' },
    caption: { fontSize: '0.75rem', color: PALETTE.textSecondary },
    button: { textTransform: 'none', fontWeight: 600 },
  },
  components: {
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: PALETTE.panel,
          border: `1px solid ${PALETTE.border}`,
        },
      },
    },
    MuiCard: {
      defaultProps: { elevation: 0 },
      styleOverrides: {
        root: {
          backgroundColor: PALETTE.panel,
          border: `1px solid ${PALETTE.border}`,
          borderRadius: 12,
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 10, paddingInline: 16, minHeight: 40 },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          backgroundColor: PALETTE.elevated,
          borderRadius: 10,
          fontSize: '0.875rem',
          '& .MuiOutlinedInput-notchedOutline': { borderColor: PALETTE.border },
          '&:hover .MuiOutlinedInput-notchedOutline': {
            borderColor: '#3A414B',
          },
        },
        input: { fontVariantNumeric: 'tabular-nums' },
      },
    },
    MuiInputLabel: {
      styleOverrides: {
        root: { fontSize: '0.8125rem', color: PALETTE.textSecondary },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 600, fontSize: '0.75rem', borderRadius: 8 },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          backgroundColor: PALETTE.elevated,
          border: `1px solid ${PALETTE.border}`,
          fontSize: '0.75rem',
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          borderColor: PALETTE.border,
          fontSize: '0.8125rem',
          fontVariantNumeric: 'tabular-nums',
          paddingBlock: 8,
        },
        head: {
          color: PALETTE.textSecondary,
          fontWeight: 600,
          backgroundColor: PALETTE.panel,
        },
      },
    },
    MuiAlert: { styleOverrides: { root: { borderRadius: 10 } } },
    MuiCssBaseline: {
      styleOverrides: {
        'html, body, #root': { height: '100%' },
        body: {
          backgroundColor: PALETTE.appBackground,
          color: PALETTE.textPrimary,
        },
        '.tabular-nums': { fontVariantNumeric: 'tabular-nums' },
        ':root': { fontFeatureSettings: TABULAR },
      },
    },
  },
}

export const theme = createTheme(options)
