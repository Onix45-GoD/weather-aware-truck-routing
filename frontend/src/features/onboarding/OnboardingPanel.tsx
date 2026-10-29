import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutlined'
import Button from '@mui/material/Button'
import Paper from '@mui/material/Paper'
import Typography from '@mui/material/Typography'
import { useId } from 'react'

import { GuideContent } from './GuideContent'

export interface OnboardingPanelProps {
  onExample: () => void
  onDismiss: () => void
  exampleLoading?: boolean | undefined
}

/**
 * First-visit guidance, shown where the results will appear.
 *
 * Two ways out: "Try an example trip" runs a real analysis so the first
 * thing a visitor sees is a real result, and "Got it" hides the panel for
 * good (remembered per browser). The header's help button brings the same
 * content back as a dialog.
 */
export function OnboardingPanel({ onExample, onDismiss, exampleLoading = false }: OnboardingPanelProps) {
  const titleId = useId()
  return (
    <Paper className="flex flex-col gap-4 p-4" aria-labelledby={titleId} data-testid="onboarding">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <Typography variant="h2" id={titleId}>
            Three steps
          </Typography>
          <Typography variant="caption" component="p">
            Up to three truck routes, ranked by the weather you would drive through.
          </Typography>
        </div>
        <div className="flex gap-2">
          <Button
            variant="contained"
            size="small"
            startIcon={<PlayCircleOutlineIcon />}
            onClick={onExample}
            disabled={exampleLoading}
          >
            {exampleLoading ? 'Running…' : 'Try an example trip'}
          </Button>
          <Button variant="outlined" size="small" onClick={onDismiss}>
            Got it
          </Button>
        </div>
      </div>
      <GuideContent />
    </Paper>
  )
}
