import Alert from '@mui/material/Alert'
import AlertTitle from '@mui/material/AlertTitle'
import Button from '@mui/material/Button'
import { Component, type ErrorInfo, type ReactNode } from 'react'

export interface ErrorBoundaryProps {
  children: ReactNode
  /** What the boundary protects, for the message: "The map", "The dashboard". */
  label: string
  /** Rendered instead of the default alert when provided. */
  fallback?: ((error: Error, reset: () => void) => ReactNode) | undefined
}

interface ErrorBoundaryState {
  error: Error | null
}

/**
 * Contains a render or effect crash to one region of the page.
 *
 * Without a boundary, any uncaught error anywhere in the tree makes React
 * unmount the *whole* application — one bad MapLibre call turns a finished
 * analysis into a blank page. With one around the map, the map shows a
 * fallback and the route cards, checkpoints and weather stay on screen,
 * which is what a driver actually needs.
 *
 * The error message is shown on screen deliberately. A blank region with a
 * silent console error is the worst of both worlds: the user cannot act on
 * it and the developer never hears about it.
 */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  override state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Keep the full stack in the console for diagnosis; the UI gets the
    // message only.
    console.error(`[${this.props.label}] crashed:`, error, info.componentStack)
  }

  private reset = () => this.setState({ error: null })

  override render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    if (this.props.fallback) return this.props.fallback(error, this.reset)

    return (
      <Alert
        severity="error"
        variant="outlined"
        role="alert"
        action={
          <Button color="inherit" size="small" onClick={this.reset}>
            Retry
          </Button>
        }
      >
        <AlertTitle>{this.props.label} failed to render</AlertTitle>
        {error.message || 'An unexpected error occurred.'}
      </Alert>
    )
  }
}
