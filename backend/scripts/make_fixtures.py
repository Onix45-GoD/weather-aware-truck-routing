"""Regenerate the synthetic provider fixtures.

Run from `backend/`:  python scripts/make_fixtures.py

Only the files named `synthetic_*.json` are produced here. The `real_*.json`
fixtures are genuine captured provider responses and are NOT regenerated --
see tests/fixtures/openmeteo/PROVENANCE.md.
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Exact unit definitions, used to build the metric fixture as a precise
# mirror of the imperial one.
KM_PER_MILE = 1.609344
MM_PER_INCH = 25.4
CM_PER_INCH = 2.54

# Values sitting exactly on the assessment's risk thresholds.
IMPERIAL_WIND = [24.999, 25.0, 35.0, 45.0, 55.0, 10.0]
IMPERIAL_GUSTS = [40.0, 41.0, 52.0, 66.0, 80.0, 15.0]
IMPERIAL_RAIN = [0.0, 0.10, 0.25, 0.50, 1.00, 1.001]
IMPERIAL_SNOW = [0.0, 0.5, 1.0, 2.0, 3.0, 3.001]
TT = ROOT / "apps/routing/tests/fixtures/tomtom"
OM = ROOT / "apps/routing/tests/fixtures/openmeteo"


def write(path: pathlib.Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"  {path.relative_to(ROOT).as_posix():<58} {path.stat().st_size:>6,} b")


def leg(points, seconds=None, metres=None):
    entry = {"points": [{"latitude": a, "longitude": b} for a, b in points]}
    if seconds is not None:
        entry["summary"] = {
            "lengthInMeters": metres,
            "travelTimeInSeconds": seconds,
        }
    return entry


def line(lat0, lon0, lat1, lon1, count, bow=0.0):
    points = []
    for step in range(count):
        t = step / (count - 1)
        points.append(
            (
                round(lat0 + (lat1 - lat0) * t + bow * (t * (1 - t)) * 4, 5),
                round(lon0 + (lon1 - lon0) * t, 5),
            )
        )
    return points


def main() -> None:
    # ---- TomTom geocoding -------------------------------------------------
    write(
        TT / "synthetic_geocode_success.json",
        {
            "summary": {"query": "denver co", "numResults": 1, "totalResults": 1},
            "results": [
                {
                    "type": "Geography",
                    "id": "SYNTHETIC-DEN",
                    "score": 0.9947,
                    "address": {
                        "municipality": "Denver",
                        "countrySubdivision": "CO",
                        "country": "United States",
                        "freeformAddress": "Denver, CO, United States",
                    },
                    "position": {"lat": 39.73915, "lon": -104.9847},
                }
            ],
        },
    )

    write(
        TT / "synthetic_geocode_no_results.json",
        {
            "summary": {"query": "zzzz nowhere", "numResults": 0, "totalResults": 0},
            "results": [],
        },
    )

    write(
        TT / "synthetic_geocode_malformed.json",
        {
            "summary": {"query": "denver"},
            "results": [{"type": "Geography", "address": {}}],
        },
    )

    # ---- TomTom routing ---------------------------------------------------
    primary = line(39.7392, -104.9903, 41.8781, -87.6298, 40)
    northern = line(39.7392, -104.9903, 41.8781, -87.6298, 40, bow=1.30)
    southern = line(39.7392, -104.9903, 41.8781, -87.6298, 40, bow=-0.95)

    write(
        TT / "synthetic_route_three_alternatives.json",
        {
            "formatVersion": "0.0.12",
            "routes": [
                {
                    "summary": {
                        "lengthInMeters": 1610000,
                        "travelTimeInSeconds": 54000,
                        "departureTime": "2026-11-02T06:00:00-06:00",
                        "arrivalTime": "2026-11-02T21:00:00-06:00",
                    },
                    "legs": [leg(primary)],
                },
                {
                    "summary": {
                        "lengthInMeters": 1707000,
                        "travelTimeInSeconds": 56400,
                        "departureTime": "2026-11-02T06:00:00-06:00",
                        "arrivalTime": "2026-11-02T21:40:00-06:00",
                    },
                    "legs": [leg(northern)],
                },
                {
                    "summary": {
                        "lengthInMeters": 1664000,
                        "travelTimeInSeconds": 59400,
                        "departureTime": "2026-11-02T06:00:00-06:00",
                        "arrivalTime": "2026-11-02T22:30:00-06:00",
                    },
                    "legs": [leg(southern)],
                },
            ],
        },
    )

    write(
        TT / "synthetic_route_two_alternatives.json",
        {
            "formatVersion": "0.0.12",
            "routes": [
                {
                    "summary": {
                        "lengthInMeters": 1610000,
                        "travelTimeInSeconds": 54000,
                    },
                    "legs": [leg(primary)],
                },
                {
                    "summary": {
                        "lengthInMeters": 1707000,
                        "travelTimeInSeconds": 56400,
                    },
                    "legs": [leg(northern)],
                },
            ],
        },
    )

    # Routes 0 and 1 are the same road: identical shape and identical summary.
    write(
        TT / "synthetic_route_duplicate_alternatives.json",
        {
            "formatVersion": "0.0.12",
            "routes": [
                {
                    "summary": {
                        "lengthInMeters": 1610000,
                        "travelTimeInSeconds": 54000,
                    },
                    "legs": [leg(primary)],
                },
                {
                    "summary": {
                        "lengthInMeters": 1610000,
                        "travelTimeInSeconds": 54000,
                    },
                    "legs": [leg(primary)],
                },
                {
                    "summary": {
                        "lengthInMeters": 1664000,
                        "travelTimeInSeconds": 59400,
                    },
                    "legs": [leg(southern)],
                },
            ],
        },
    )

    # Two legs, so genuine per-leg timings exist.
    mid = len(primary) // 2
    write(
        TT / "synthetic_route_two_legs.json",
        {
            "formatVersion": "0.0.12",
            "routes": [
                {
                    "summary": {
                        "lengthInMeters": 1610000,
                        "travelTimeInSeconds": 54000,
                    },
                    "legs": [
                        leg(primary[: mid + 1], seconds=36000, metres=800000),
                        leg(primary[mid:], seconds=18000, metres=810000),
                    ],
                }
            ],
        },
    )

    # Encoded-polyline representation. The string is the canonical Google
    # example, which the domain decoder is already tested against.
    write(
        TT / "synthetic_route_encoded_polyline.json",
        {
            "formatVersion": "0.0.12",
            "routes": [
                {
                    "summary": {
                        "lengthInMeters": 1610000,
                        "travelTimeInSeconds": 54000,
                    },
                    "encodedPolyline": "_p~iF~ps|U_ulLnnqC_mqNvxq" + chr(96) + "@",
                    "encodedPolylinePrecision": 5,
                }
            ],
        },
    )

    write(TT / "synthetic_route_empty.json", {"formatVersion": "0.0.12", "routes": []})
    write(
        TT / "synthetic_route_malformed.json",
        {"formatVersion": "0.0.12", "routes": [{"summary": {"lengthInMeters": "far"}}]},
    )

    # ---- Open-Meteo synthetic edge cases ----------------------------------
    hours = [
        "2026-11-02T00:00",
        "2026-11-02T01:00",
        "2026-11-02T02:00",
        "2026-11-02T03:00",
        "2026-11-02T04:00",
        "2026-11-02T05:00",
    ]
    imperial = {
        "time": "iso8601",
        "wind_speed_10m": "mp/h",
        "wind_gusts_10m": "mp/h",
        "rain": "inch",
        "showers": "inch",
        "snowfall": "inch",
    }

    # Values sitting exactly on the assessment's risk boundaries.
    write(
        OM / "synthetic_boundaries.json",
        {
            "latitude": 40.0,
            "longitude": -100.0,
            "utc_offset_seconds": 0,
            "timezone": "GMT",
            "elevation": 900.0,
            "hourly_units": imperial,
            "hourly": {
                "time": hours,
                "wind_speed_10m": IMPERIAL_WIND,
                "wind_gusts_10m": IMPERIAL_GUSTS,
                "rain": IMPERIAL_RAIN,
                "showers": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "snowfall": IMPERIAL_SNOW,
            },
        },
    )

    # The same physical conditions expressed in the API's default metric
    # units, so the cm -> inch conversion can be proved against the imperial
    # fixture above rather than asserted.
    write(
        OM / "synthetic_boundaries_metric.json",
        {
            "latitude": 40.0,
            "longitude": -100.0,
            "utc_offset_seconds": 0,
            "timezone": "GMT",
            "elevation": 900.0,
            "hourly_units": {
                "time": "iso8601",
                "wind_speed_10m": "km/h",
                "wind_gusts_10m": "km/h",
                "rain": "mm",
                "showers": "mm",
                "snowfall": "cm",
            },
            # Exact equivalents of the imperial fixture, so any difference the
            # tests find is a conversion error rather than rounded input.
            # KM_PER_MILE, MM_PER_INCH and CM_PER_INCH are exact definitions.
            "hourly": {
                "time": hours,
                "wind_speed_10m": [v * KM_PER_MILE for v in IMPERIAL_WIND],
                "wind_gusts_10m": [v * KM_PER_MILE for v in IMPERIAL_GUSTS],
                "rain": [v * MM_PER_INCH for v in IMPERIAL_RAIN],
                "showers": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "snowfall": [v * CM_PER_INCH for v in IMPERIAL_SNOW],
            },
        },
    )

    write(
        OM / "synthetic_missing_values.json",
        {
            "latitude": 40.0,
            "longitude": -100.0,
            "utc_offset_seconds": 0,
            "timezone": "GMT",
            "hourly_units": imperial,
            "hourly": {
                "time": hours[:4],
                "wind_speed_10m": [12.0, None, 30.0, None],
                "wind_gusts_10m": [18.0, None, 44.0, None],
                "rain": [0.0, None, None, 0.2],
                "showers": [0.0, None, None, 0.1],
                "snowfall": [0.0, None, 0.6, None],
            },
        },
    )

    write(
        OM / "synthetic_unknown_units.json",
        {
            "latitude": 40.0,
            "longitude": -100.0,
            "timezone": "GMT",
            "hourly_units": {**imperial, "snowfall": "furlongs"},
            "hourly": {
                "time": hours[:2],
                "wind_speed_10m": [10.0, 11.0],
                "wind_gusts_10m": [15.0, 16.0],
                "rain": [0.0, 0.0],
                "showers": [0.0, 0.0],
                "snowfall": [0.1, 0.2],
            },
        },
    )

    write(OM / "synthetic_malformed.json", {"latitude": 40.0, "longitude": -100.0})

    write(
        OM / "synthetic_length_mismatch.json",
        {
            "latitude": 40.0,
            "longitude": -100.0,
            "timezone": "GMT",
            "hourly_units": imperial,
            "hourly": {
                "time": hours[:3],
                "wind_speed_10m": [1.0, 2.0],
                "wind_gusts_10m": [1.0, 2.0, 3.0],
                "rain": [0.0, 0.0, 0.0],
                "showers": [0.0, 0.0, 0.0],
                "snowfall": [0.0, 0.0, 0.0],
            },
        },
    )


if __name__ == "__main__":
    main()
