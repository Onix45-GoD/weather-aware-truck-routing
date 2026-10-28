"""Provider adapters: all external I/O lives here.

Adapters translate third-party responses into the domain's value objects and
nothing more. No risk classification, no mileage aggregation, no ranking --
that logic belongs to :mod:`apps.routing.domain` and must not be duplicated
here, or the two copies will drift.

The dependency direction is strictly one-way: providers may import from
``domain`` (to build its value objects), but ``domain`` never imports from
here.
"""
