"""Pure domain core for weather-aware truck routing.

Everything in this package is a deterministic transformation of value objects.
It imports only the Python standard library: no Django, no HTTP clients, no
environment variables, no wall-clock reads and no randomness. That makes the
scoring logic -- the part the assessment weights most heavily -- provable in
isolation and completely independent of any external provider.
"""
