"""Timezone handling for the departure time.

A driver thinks in local wall-clock time -- "I leave at six" -- not in UTC
offsets. Making the client compute an offset also makes the client responsible
for daylight saving, which is where it goes wrong: America/Denver is -06:00 on
2026-11-01 and -07:00 on 2026-11-02, so an offset derived from "today" is an
hour out across that boundary, and every checkpoint forecast with it.

Sending an IANA zone name instead moves that problem to a library that
actually has the rules.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from django.test import Client

URL = "/api/v1/route-analysis"

BASE = {
    "origin": "Denver",
    "destination": "Chicago",
    "load_weight_lb": 42000,
    "checkpoint_interval_miles": 50,
}


def post(**overrides):
    return Client().post(
        URL, data=json.dumps({**BASE, **overrides}), content_type="application/json"
    )


class TestLocalWallClockInput:
    def test_a_named_zone_resolves_local_time_to_the_right_instant(self) -> None:
        """06:00 in Denver on 2026-11-02 is 13:00Z -- MST, not MDT."""
        response = post(
            departure_at="2026-11-02T06:00:00",
            departure_timezone="America/Denver",
        )
        assert response.status_code == 200, response.content

        request = response.json()["request"]
        assert request["departure_at"] == "2026-11-02T13:00:00+00:00"
        assert request["departure_timezone"] == "America/Denver"

    def test_daylight_saving_is_applied_from_the_date_not_from_today(self) -> None:
        """The exact trap a client-computed offset falls into.

        Same wall-clock time two days apart, on either side of the DST change,
        must map to instants an hour apart in UTC.
        """
        before = post(
            departure_at="2026-10-31T06:00:00", departure_timezone="America/Denver"
        ).json()["request"]["departure_at"]
        after = post(
            departure_at="2026-11-02T06:00:00", departure_timezone="America/Denver"
        ).json()["request"]["departure_at"]

        assert before == "2026-10-31T12:00:00+00:00"  # MDT, -06:00
        assert after == "2026-11-02T13:00:00+00:00"  # MST, -07:00

    @pytest.mark.parametrize(
        ("zone", "expected_utc"),
        [
            ("UTC", "2026-11-02T06:00:00+00:00"),
            ("America/Denver", "2026-11-02T13:00:00+00:00"),
            ("America/New_York", "2026-11-02T11:00:00+00:00"),
            ("Europe/London", "2026-11-02T06:00:00+00:00"),
            ("Asia/Tokyo", "2026-11-01T21:00:00+00:00"),
            ("Asia/Kolkata", "2026-11-02T00:30:00+00:00"),
        ],
    )
    def test_every_zone_the_customer_might_pick(
        self, zone: str, expected_utc: str
    ) -> None:
        response = post(
            departure_at="2026-11-02T06:00:00", departure_timezone=zone
        )
        assert response.status_code == 200, response.content
        assert response.json()["request"]["departure_at"] == expected_utc

    def test_the_response_echoes_the_time_back_in_local_form(self) -> None:
        """So the driver can confirm we read their input as they meant it."""
        request = post(
            departure_at="2026-11-02T06:00:00", departure_timezone="America/Denver"
        ).json()["request"]

        assert request["departure_at_local"] == "2026-11-02T06:00:00-07:00"
        assert request["departure_timezone"] == "America/Denver"

    def test_arrival_is_echoed_locally_too(self) -> None:
        body = post(
            departure_at="2026-11-02T06:00:00", departure_timezone="America/Denver"
        ).json()
        summary = body["routes"][0]["summary"]

        assert summary["arrival_at"].endswith("+00:00")
        assert summary["arrival_at_local"] is not None
        # Same instant, two renderings.
        assert datetime.fromisoformat(
            summary["arrival_at_local"]
        ) == datetime.fromisoformat(summary["arrival_at"])


class TestOffsetInputStillWorks:
    def test_an_explicit_offset_is_honoured(self) -> None:
        request = post(departure_at="2026-11-02T06:00:00-06:00").json()["request"]
        assert request["departure_at"] == "2026-11-02T12:00:00+00:00"

    def test_an_offset_needs_no_timezone(self) -> None:
        assert post(departure_at="2026-11-02T12:00:00Z").status_code == 200

    def test_a_timezone_alongside_an_offset_is_used_only_for_display(self) -> None:
        """The offset fixes the instant; the zone just formats it."""
        request = post(
            departure_at="2026-11-02T12:00:00Z",
            departure_timezone="Asia/Tokyo",
        ).json()["request"]

        assert request["departure_at"] == "2026-11-02T12:00:00+00:00"
        assert request["departure_at_local"] == "2026-11-02T21:00:00+09:00"

    def test_local_echo_is_null_without_a_timezone(self) -> None:
        """Explicit null, not a missing key -- a typed client can rely on it."""
        request = post(departure_at="2026-11-02T12:00:00Z").json()["request"]
        assert request["departure_timezone"] is None
        assert request["departure_at_local"] is None


class TestMissingTimezone:
    def test_a_naive_time_without_a_zone_is_rejected(self) -> None:
        """Guessing would move the trip by hours and change the answer."""
        response = post(departure_at="2026-11-02T06:00:00")
        assert response.status_code == 400

        details = response.json()["error"]["details"]
        assert "departure_timezone" in details
        assert "America/Denver" in str(details["departure_timezone"])

    def test_a_blank_timezone_is_treated_as_absent(self) -> None:
        response = post(departure_at="2026-11-02T06:00:00", departure_timezone="")
        assert response.status_code == 400
        assert "departure_timezone" in response.json()["error"]["details"]

    def test_an_unknown_zone_is_rejected_with_a_helpful_message(self) -> None:
        response = post(
            departure_at="2026-11-02T06:00:00", departure_timezone="Mars/Olympus"
        )
        assert response.status_code == 400
        details = response.json()["error"]["details"]
        assert "departure_timezone" in details
        assert "Unknown timezone" in str(details["departure_timezone"])


class TestDaylightSavingEdges:
    """Twice a year a local time is ambiguous or impossible.

    `zoneinfo` resolves both silently. Silent is the problem: the driver would
    get an analysis for an hour they did not ask for.
    """

    def test_an_ambiguous_time_picks_the_earlier_and_says_so(self) -> None:
        """2026-11-01 01:30 happens twice in Denver when clocks go back."""
        body = post(
            departure_at="2026-11-01T01:30:00",
            departure_timezone="America/Denver",
        ).json()

        warning = next(
            w for w in body["warnings"] if w["code"] == "AMBIGUOUS_LOCAL_TIME"
        )
        assert "occurs twice" in warning["message"]
        # The earlier occurrence is MDT (-06:00) -> 07:30Z.
        assert body["request"]["departure_at"] == "2026-11-01T07:30:00+00:00"

    def test_a_nonexistent_time_is_shifted_and_flagged(self) -> None:
        """2026-03-08 02:30 does not exist in Denver; clocks jump 02:00->03:00."""
        body = post(
            departure_at="2026-03-08T02:30:00",
            departure_timezone="America/Denver",
        ).json()

        warning = next(
            w for w in body["warnings"] if w["code"] == "NONEXISTENT_LOCAL_TIME"
        )
        assert "does not exist" in warning["message"]
        assert "03:30" in warning["message"]

    def test_an_ordinary_time_raises_no_dst_warning(self) -> None:
        body = post(
            departure_at="2026-11-02T06:00:00",
            departure_timezone="America/Denver",
        ).json()
        codes = {w["code"] for w in body["warnings"]}
        assert "AMBIGUOUS_LOCAL_TIME" not in codes
        assert "NONEXISTENT_LOCAL_TIME" not in codes


class TestTimezoneDoesNotChangeTheAnalysis:
    def test_the_same_instant_expressed_two_ways_analyses_identically(self) -> None:
        """A timezone labels an instant; it cannot change one.

        Denver 06:00 on 2026-11-02 and 13:00Z are the same moment, so the
        risk, ranking and recommendation must match exactly.
        """
        local = post(
            departure_at="2026-11-02T06:00:00",
            departure_timezone="America/Denver",
        ).json()
        utc = post(departure_at="2026-11-02T13:00:00Z").json()

        assert local["recommended_route_id"] == utc["recommended_route_id"]
        for left, right in zip(local["routes"], utc["routes"]):
            assert left["metrics"] == right["metrics"]
            assert [c["eta"] for c in left["checkpoints"]] == [
                c["eta"] for c in right["checkpoints"]
            ]

    def test_the_forecast_offset_applies_on_top_of_local_time(self) -> None:
        body = post(
            departure_at="2026-11-02T06:00:00",
            departure_timezone="America/Denver",
            forecast_offset_hours=6,
        ).json()["request"]

        assert body["departure_at"] == "2026-11-02T13:00:00+00:00"
        assert body["effective_departure_at"] == "2026-11-02T19:00:00+00:00"
        assert body["effective_departure_at_local"] == "2026-11-02T12:00:00-07:00"


class TestCheckpointTimesRemainUtc:
    def test_every_checkpoint_eta_is_utc_regardless_of_input_zone(self) -> None:
        """One canonical timestamp format on the wire.

        Checkpoint ETAs are not duplicated in local form: that would roughly
        double the payload for data a client can format itself from the UTC
        value plus `departure_timezone`.
        """
        body = post(
            departure_at="2026-11-02T06:00:00", departure_timezone="Asia/Tokyo"
        ).json()

        for route in body["routes"]:
            for checkpoint in route["checkpoints"]:
                assert checkpoint["eta"].endswith("+00:00")
                assert "eta_local" not in checkpoint

    def test_a_client_can_reconstruct_local_times_from_what_is_returned(
        self,
    ) -> None:
        body = post(
            departure_at="2026-11-02T06:00:00", departure_timezone="America/Denver"
        ).json()
        zone = ZoneInfo(body["request"]["departure_timezone"])

        first = body["routes"][0]["checkpoints"][0]
        local = datetime.fromisoformat(first["eta"]).astimezone(zone)
        assert local.isoformat() == body["request"]["departure_at_local"]
        assert local.astimezone(UTC) == datetime.fromisoformat(first["eta"])
