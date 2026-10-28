/**
 * Risk vocabulary shared with the backend domain layer.
 *
 * These are presentation-side mirrors of
 * `apps/routing/domain/models.py::RiskLevel`. From Milestone 3 the response
 * types themselves are generated from the backend's OpenAPI schema, so this
 * file stays deliberately small: the names and their display order only.
 *
 * No classification logic lives on the frontend. Risk levels arrive from the
 * API already decided, and the UI only ever renders them.
 */

export const RISK_LEVELS = [
  'LOW',
  'MODERATE',
  'HIGH',
  'SEVERE',
  'NO_TRAVEL',
  'UNKNOWN',
] as const

export type RiskLevel = (typeof RISK_LEVELS)[number]

/** Severity order for sorting and legends. `UNKNOWN` sorts last deliberately:
 *  it is an absence of information, not a severity. */
export const RISK_LEVEL_ORDER: readonly RiskLevel[] = RISK_LEVELS

export const CHECKPOINT_INTERVALS = [10, 25, 50] as const

export type CheckpointInterval = (typeof CHECKPOINT_INTERVALS)[number]
