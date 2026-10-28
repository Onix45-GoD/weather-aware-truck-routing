"""Orchestration: the layer that knows both providers and the domain.

Providers fetch, the domain decides, and this layer carries values between
them. It contains no risk thresholds, no ranking rules and no checkpoint
maths -- every one of those lives in :mod:`apps.routing.domain` and is reused
here rather than reimplemented. An architectural test asserts that.
"""
