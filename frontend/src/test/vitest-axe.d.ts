/**
 * `vitest-axe` 0.1 types its matcher against the pre-1.0 `Vi` namespace,
 * which Vitest 5 no longer has. This is the same declaration against the
 * current module augmentation point.
 */
import 'vitest'

declare module 'vitest' {
  interface Assertion<T = unknown> {
    toHaveNoViolations(): T
  }
  interface AsymmetricMatchersContaining {
    toHaveNoViolations(): void
  }
}
