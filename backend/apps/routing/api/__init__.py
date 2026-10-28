"""HTTP boundary: request validation, response shaping, error mapping.

Nothing in here makes a routing, weather or risk decision. It translates
between JSON and the orchestration layer's value objects, and maps typed
errors to status codes.
"""
