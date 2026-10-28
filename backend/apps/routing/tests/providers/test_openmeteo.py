"""Contract tests for the Open-Meteo weather adapter.

Snowfall units have their own module -- see ``test_snowfall_units.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from apps.routing.domain.models import Coordinate
from apps.routing.providers.errors import InvalidProviderResponseError
from apps.routing.providers.openmeteo import (
    COORDINATE_PRECISION,
    MAX_FORECAST_DAYS,
    OpenMeteoWeatherProvider,
    forecast_window,
    quantize,
)
from apps.routing.tests.providers.conftest import CHICAGO, DENVER, load_fixture

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

START = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
END = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)
FIXED_NOW = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)


def om(name: str):
    return load_fixture("openmeteo", name)


@pytest.fixture
def provider(fast_client):
    return OpenMeteoWeatherProvider(
        client=fast_client("open-meteo"), now=lambda: FIXED_NOW
    )


def mock_forecast(payload):
    return respx.get(url__startswith=FORECAST_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )


class TestRequestConstruction:
    @respx.mock
    def test_requests_the_variables_the_risk_engine_needs(self, provider) -> None:
        route = mock_forecast(om("synthetic_boundaries.json"))
        provider.hourly([DENVER], START, END)

        hourly = route.calls.last.request.url.params["hourly"].split(",")
        assert "wind_speed_10m" in hourly
        assert "rain" in hourly
        assert "showers" in hourly
        assert "snowfall" in hourly
        assert "wind_gusts_10m" in hourly

    @respx.mock
    def test_requests_imperial_units_directly(self, provider) -> None:
        """No conversion on the happy path means no conversion drift."""
        route = mock_forecast(om("synthetic_boundaries.json"))
        provider.hourly([DENVER], START, END)

        params = route.calls.last.request.url.params
        assert params["wind_speed_unit"] == "mph"
        assert params["precipitation_unit"] == "inch"

    @respx.mock
    def test_requests_utc_timestamps(self, provider) -> None:
        route = mock_forecast(om("synthetic_boundaries.json"))
        provider.hourly([DENVER], START, END)
        assert route.calls.last.request.url.params["timezone"] == "UTC"

    @respx.mock
    def test_does_not_request_precipitation_as_the_rain_rate(self, provider) -> None:
        """`precipitation` bundles snow's liquid equivalent; using it as the
        rain rate would double-count snowy hours."""
        route = mock_forecast(om("synthetic_boundaries.json"))
        provider.hourly([DENVER], START, END)
        assert "precipitation" not in route.calls.last.request.url.params[
            "hourly"
        ].split(",")

    @respx.mock
    def test_sends_no_api_key(self, provider) -> None:
        """Open-Meteo needs none, so there is no credential to leak."""
        route = mock_forecast(om("synthetic_boundaries.json"))
        provider.hourly([DENVER], START, END)
        params = route.calls.last.request.url.params
        assert not {"key", "apikey", "api_key", "token"} & set(params.keys())

    @respx.mock
    def test_forecast_days_covers_the_requested_window(self, provider) -> None:
        route = mock_forecast(om("synthetic_boundaries.json"))
        provider.hourly([DENVER], START, START + timedelta(days=3))
        assert int(route.calls.last.request.url.params["forecast_days"]) == 4

    @respx.mock
    def test_forecast_days_is_capped_at_the_provider_horizon(self, provider) -> None:
        route = mock_forecast(om("synthetic_boundaries.json"))
        provider.hourly([DENVER], START, START + timedelta(days=90))
        assert int(route.calls.last.request.url.params["forecast_days"]) == MAX_FORECAST_DAYS

    @respx.mock
    def test_past_days_is_requested_when_the_window_starts_earlier(
        self, fast_client
    ) -> None:
        later = OpenMeteoWeatherProvider(
            client=fast_client("open-meteo"),
            now=lambda: datetime(2026, 11, 4, 0, 0, tzinfo=UTC),
        )
        route = mock_forecast(om("synthetic_boundaries.json"))
        later.hourly([DENVER], START, END)
        assert int(route.calls.last.request.url.params["past_days"]) == 2

    def test_naive_datetimes_are_rejected(self, provider) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            provider.hourly([DENVER], datetime(2026, 11, 2), END)

    def test_reversed_window_is_rejected(self, provider) -> None:
        with pytest.raises(ValueError, match="must not precede"):
            provider.hourly([DENVER], END, START)

    def test_no_coordinates_makes_no_request(self, provider) -> None:
        assert provider.hourly([], START, END) == ()


class TestParsing:
    @respx.mock
    def test_builds_timezone_aware_utc_timestamps(self, provider) -> None:
        mock_forecast(om("synthetic_boundaries.json"))
        forecast = provider.hourly([DENVER], START, END)[0]

        assert forecast.times[0] == datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
        assert all(t.tzinfo is not None for t in forecast.times)
        assert all(t.utcoffset() == timedelta(0) for t in forecast.times)

    @respx.mock
    def test_wind_is_carried_through_unconverted(self, provider) -> None:
        mock_forecast(om("synthetic_boundaries.json"))
        samples = provider.hourly([DENVER], START, END)[0].samples
        assert [s.wind_mph for s in samples] == pytest.approx(
            [24.999, 25.0, 35.0, 45.0, 55.0, 10.0]
        )

    @respx.mock
    def test_rain_sums_large_scale_and_convective(self, provider) -> None:
        """Open-Meteo splits rain and showers; using `rain` alone would
        under-report thunderstorms."""
        mock_forecast(
            {
                "latitude": 40.0,
                "longitude": -100.0,
                "hourly_units": {
                    "time": "iso8601",
                    "wind_speed_10m": "mp/h",
                    "wind_gusts_10m": "mp/h",
                    "rain": "inch",
                    "showers": "inch",
                    "snowfall": "inch",
                },
                "hourly": {
                    "time": ["2026-11-02T00:00"],
                    "wind_speed_10m": [5.0],
                    "wind_gusts_10m": [8.0],
                    "rain": [0.10],
                    "showers": [0.20],
                    "snowfall": [0.0],
                },
            }
        )
        sample = provider.hourly([DENVER], START, END)[0].samples[0]
        assert sample.rain_in_hr == pytest.approx(0.30)

    @respx.mock
    def test_gusts_are_preserved_separately_from_sustained_wind(
        self, provider
    ) -> None:
        mock_forecast(om("synthetic_boundaries.json"))
        sample = provider.hourly([DENVER], START, END)[0].samples[0]
        assert sample.wind_mph == pytest.approx(24.999)
        assert sample.wind_gust_mph == pytest.approx(40.0)

    @respx.mock
    def test_forecast_time_is_stamped_on_each_sample(self, provider) -> None:
        mock_forecast(om("synthetic_boundaries.json"))
        forecast = provider.hourly([DENVER], START, END)[0]
        assert all(
            sample.forecast_time == time
            for sample, time in zip(forecast.samples, forecast.times)
        )

    @respx.mock
    def test_resolved_coordinate_records_the_model_grid_cell(self, provider) -> None:
        mock_forecast(om("synthetic_boundaries.json"))
        forecast = provider.hourly([DENVER], START, END)[0]
        assert forecast.resolved_coordinate == Coordinate(40.0, -100.0)
        assert forecast.coordinate != forecast.resolved_coordinate

    @respx.mock
    def test_elevation_is_preserved(self, provider) -> None:
        mock_forecast(om("synthetic_boundaries.json"))
        assert provider.hourly([DENVER], START, END)[0].elevation_m == 900.0


class TestMissingValues:
    @respx.mock
    def test_nulls_become_none_not_zero(self, provider) -> None:
        """Zero means calm and dry, which classifies LOW. A gap must not."""
        mock_forecast(om("synthetic_missing_values.json"))
        samples = provider.hourly([DENVER], START, END)[0].samples

        assert samples[1].wind_mph is None
        assert samples[1].rain_in_hr is None
        assert samples[1].snow_in_hr is None
        assert samples[1].wind_mph != 0.0

    @respx.mock
    def test_partially_missing_hours_keep_what_is_known(self, provider) -> None:
        mock_forecast(om("synthetic_missing_values.json"))
        samples = provider.hourly([DENVER], START, END)[0].samples

        assert samples[2].wind_mph == pytest.approx(30.0)
        assert samples[2].rain_in_hr is None
        assert samples[2].snow_in_hr == pytest.approx(0.6)

    @respx.mock
    def test_rain_is_missing_only_when_both_components_are(self, provider) -> None:
        mock_forecast(om("synthetic_missing_values.json"))
        samples = provider.hourly([DENVER], START, END)[0].samples
        # hour 3: rain=0.2, showers=0.1 -> 0.3; hour 2: both null -> None
        assert samples[3].rain_in_hr == pytest.approx(0.3)
        assert samples[2].rain_in_hr is None

    @respx.mock
    def test_an_absent_variable_becomes_unknown_for_every_hour(
        self, provider
    ) -> None:
        payload = om("synthetic_boundaries.json")
        del payload["hourly"]["snowfall"]
        mock_forecast(payload)
        samples = provider.hourly([DENVER], START, END)[0].samples
        assert all(sample.snow_in_hr is None for sample in samples)
        assert samples[0].wind_mph is not None  # the rest still parses

    @respx.mock
    def test_nan_is_treated_as_missing(self, provider) -> None:
        """A bare `NaN` literal is not valid JSON but parsers accept it.

        Sent as raw content because httpx's encoder refuses to serialise NaN,
        which is also why this path is defensive rather than observed.
        """
        body = (
            '{"latitude":40.0,"longitude":-100.0,'
            '"hourly_units":{"time":"iso8601","wind_speed_10m":"mp/h",'
            '"wind_gusts_10m":"mp/h","rain":"inch","showers":"inch",'
            '"snowfall":"inch"},'
            '"hourly":{"time":["2026-11-02T00:00"],"wind_speed_10m":[NaN],'
            '"wind_gusts_10m":[1.0],"rain":[0.0],"showers":[0.0],'
            '"snowfall":[0.0]}}'
        )
        respx.get(url__startswith=FORECAST_URL).mock(
            return_value=httpx.Response(
                200, content=body, headers={"content-type": "application/json"}
            )
        )
        assert provider.hourly([DENVER], START, END)[0].samples[0].wind_mph is None


class TestMalformedResponses:
    @respx.mock
    @pytest.mark.parametrize(
        "name",
        ["synthetic_malformed.json", "synthetic_length_mismatch.json"],
    )
    def test_structural_problems_raise_typed_errors(self, provider, name) -> None:
        mock_forecast(om(name))
        with pytest.raises(InvalidProviderResponseError):
            provider.hourly([DENVER], START, END)

    @respx.mock
    def test_a_non_object_entry_raises(self, provider) -> None:
        mock_forecast(["not-an-object"])
        with pytest.raises(InvalidProviderResponseError):
            provider.hourly([DENVER], START, END)

    @respx.mock
    def test_a_wrong_location_count_raises(self, provider) -> None:
        mock_forecast([om("synthetic_boundaries.json")])
        with pytest.raises(InvalidProviderResponseError, match="requested 2"):
            provider.hourly([DENVER, CHICAGO], START, END)

    @respx.mock
    def test_a_non_numeric_measurement_raises(self, provider) -> None:
        payload = om("synthetic_boundaries.json")
        payload["hourly"]["wind_speed_10m"] = ["breezy"] * 6
        mock_forecast(payload)
        with pytest.raises(InvalidProviderResponseError, match="wind_speed_10m"):
            provider.hourly([DENVER], START, END)

    @respx.mock
    def test_a_bad_timestamp_raises(self, provider) -> None:
        payload = om("synthetic_boundaries.json")
        payload["hourly"]["time"] = ["not-a-time"] * 6
        mock_forecast(payload)
        with pytest.raises(InvalidProviderResponseError, match="ISO-8601"):
            provider.hourly([DENVER], START, END)

    @respx.mock
    def test_a_non_list_column_raises(self, provider) -> None:
        payload = om("synthetic_boundaries.json")
        payload["hourly"]["rain"] = "wet"
        mock_forecast(payload)
        with pytest.raises(InvalidProviderResponseError, match="must be a list"):
            provider.hourly([DENVER], START, END)

    @respx.mock
    def test_an_out_of_range_resolved_position_raises(self, provider) -> None:
        payload = om("synthetic_boundaries.json")
        payload["latitude"] = 240.0
        mock_forecast(payload)
        with pytest.raises(InvalidProviderResponseError, match="out-of-range"):
            provider.hourly([DENVER], START, END)


class TestBatchingAndAssociation:
    @respx.mock
    def test_multiple_locations_go_in_one_request(self, provider) -> None:
        route = mock_forecast([om("synthetic_boundaries.json")] * 2)
        provider.hourly([DENVER, CHICAGO], START, END)

        assert route.call_count == 1
        params = route.calls.last.request.url.params
        assert len(params["latitude"].split(",")) == 2
        assert len(params["longitude"].split(",")) == 2

    @respx.mock
    def test_results_are_associated_by_index_not_by_coordinate(
        self, provider
    ) -> None:
        """The provider snaps coordinates to its grid, so matching them back
        would fail; proximity matching could pair the wrong checkpoint with
        the wrong forecast."""
        first = om("synthetic_boundaries.json")
        second = om("synthetic_boundaries.json")
        second["hourly"]["wind_speed_10m"] = [1.0] * 6
        # Both entries report grid positions nowhere near either request.
        first["latitude"], first["longitude"] = 0.0, 0.0
        second["latitude"], second["longitude"] = 0.0, 0.0
        mock_forecast([first, second])

        results = provider.hourly([DENVER, CHICAGO], START, END)
        assert results[0].samples[0].wind_mph == pytest.approx(24.999)
        assert results[1].samples[0].wind_mph == pytest.approx(1.0)
        assert results[0].coordinate != results[1].coordinate

    @respx.mock
    def test_requests_are_chunked_at_the_configured_size(self, fast_client) -> None:
        provider = OpenMeteoWeatherProvider(
            client=fast_client("open-meteo"), chunk_size=2, now=lambda: FIXED_NOW
        )
        coordinates = [
            Coordinate(latitude=40.0 + index, longitude=-100.0) for index in range(5)
        ]
        route = respx.get(url__startswith=FORECAST_URL).mock(
            side_effect=[
                httpx.Response(200, json=[om("synthetic_boundaries.json")] * 2),
                httpx.Response(200, json=[om("synthetic_boundaries.json")] * 2),
                httpx.Response(200, json=om("synthetic_boundaries.json")),
            ]
        )
        results = provider.hourly(coordinates, START, END)

        assert route.call_count == 3
        assert len(results) == 5

    @respx.mock
    def test_duplicate_coordinates_collapse_into_one_lookup(self, provider) -> None:
        route = mock_forecast(om("synthetic_boundaries.json"))
        results = provider.hourly([DENVER, DENVER, DENVER], START, END)

        assert route.call_count == 1
        assert len(route.calls.last.request.url.params["latitude"].split(",")) == 1
        assert len(results) == 3

    @respx.mock
    def test_output_length_always_matches_input_length(self, provider) -> None:
        mock_forecast([om("synthetic_boundaries.json")] * 2)
        assert len(provider.hourly([DENVER, CHICAGO, DENVER], START, END)) == 3

    def test_rejects_a_nonsensical_chunk_size(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            OpenMeteoWeatherProvider(chunk_size=0)


class TestCoordinatePrecision:
    def test_precision_is_finer_than_the_providers_model_grid(self) -> None:
        """Two decimal places is ~1.1 km; the finest model grid is ~2 km."""
        assert COORDINATE_PRECISION == 2

    def test_quantize_rounds_to_the_shared_grid(self) -> None:
        assert quantize(Coordinate(39.746895, -104.987076)) == Coordinate(39.75, -104.99)

    def test_points_a_kilometre_apart_stay_distinct(self) -> None:
        """A coarser key would merge genuinely different checkpoints."""
        near = Coordinate(latitude=40.00, longitude=-100.00)
        far = Coordinate(latitude=40.02, longitude=-100.00)  # ~2.2 km north
        assert quantize(near) != quantize(far)

    def test_points_metres_apart_are_merged(self) -> None:
        a = Coordinate(latitude=40.0001, longitude=-100.0001)
        b = Coordinate(latitude=40.0002, longitude=-100.0002)
        assert quantize(a) == quantize(b)

    @respx.mock
    def test_near_identical_checkpoints_share_a_lookup(self, provider) -> None:
        route = mock_forecast(om("synthetic_boundaries.json"))
        provider.hourly(
            [
                Coordinate(latitude=40.0001, longitude=-100.0001),
                Coordinate(latitude=40.0002, longitude=-100.0002),
            ],
            START,
            END,
        )
        assert len(route.calls.last.request.url.params["latitude"].split(",")) == 1


class TestCaching:
    @respx.mock
    def test_an_identical_window_is_served_from_cache(self, fast_client) -> None:
        provider = OpenMeteoWeatherProvider(
            client=fast_client("open-meteo", cache_ttl_seconds=600),
            now=lambda: FIXED_NOW,
        )
        route = mock_forecast(om("synthetic_boundaries.json"))
        provider.hourly([DENVER], START, END)
        provider.hourly([DENVER], START, END)
        assert route.call_count == 1

    @respx.mock
    def test_a_different_location_misses_the_cache(self, fast_client) -> None:
        provider = OpenMeteoWeatherProvider(
            client=fast_client("open-meteo", cache_ttl_seconds=600),
            now=lambda: FIXED_NOW,
        )
        route = mock_forecast(om("synthetic_boundaries.json"))
        provider.hourly([DENVER], START, END)
        provider.hourly([CHICAGO], START, END)
        assert route.call_count == 2


class TestForecastWindow:
    def test_covers_the_slider_when_the_trip_is_short(self) -> None:
        departure = datetime(2026, 11, 2, 6, tzinfo=UTC)
        start, end = forecast_window(departure, departure + timedelta(hours=4))
        assert start == departure
        assert end == departure + timedelta(hours=48)

    def test_covers_the_trip_when_it_outlasts_the_slider(self) -> None:
        departure = datetime(2026, 11, 2, 6, tzinfo=UTC)
        arrival = departure + timedelta(hours=70)
        _start, end = forecast_window(departure, arrival)
        assert end == arrival

    def test_rejects_naive_datetimes(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            forecast_window(datetime(2026, 11, 2, 6), datetime(2026, 11, 2, 9))


class TestParsingEdgeCases:
    @respx.mock
    def test_a_non_string_timestamp_raises(self, provider) -> None:
        payload = om("synthetic_boundaries.json")
        payload["hourly"]["time"] = [12345] * 6
        mock_forecast(payload)
        with pytest.raises(InvalidProviderResponseError, match="must be strings"):
            provider.hourly([DENVER], START, END)

    @respx.mock
    def test_a_missing_time_series_raises(self, provider) -> None:
        payload = om("synthetic_boundaries.json")
        del payload["hourly"]["time"]
        mock_forecast(payload)
        with pytest.raises(InvalidProviderResponseError, match="hourly.time"):
            provider.hourly([DENVER], START, END)

    @respx.mock
    def test_a_timestamp_with_an_explicit_offset_is_normalised_to_utc(
        self, provider
    ) -> None:
        payload = om("synthetic_boundaries.json")
        payload["hourly"]["time"] = [
            "2026-11-02T00:00:00-06:00",
            "2026-11-02T01:00:00-06:00",
            "2026-11-02T02:00:00-06:00",
            "2026-11-02T03:00:00-06:00",
            "2026-11-02T04:00:00-06:00",
            "2026-11-02T05:00:00-06:00",
        ]
        mock_forecast(payload)
        forecast = provider.hourly([DENVER], START, END)[0]
        assert forecast.times[0] == datetime(2026, 11, 2, 6, 0, tzinfo=UTC)

    @respx.mock
    def test_a_missing_grid_position_falls_back_to_the_request(
        self, provider
    ) -> None:
        payload = om("synthetic_boundaries.json")
        del payload["latitude"]
        mock_forecast(payload)
        forecast = provider.hourly([DENVER], START, END)[0]
        assert forecast.resolved_coordinate == forecast.coordinate

    @respx.mock
    def test_absent_elevation_is_tolerated(self, provider) -> None:
        payload = om("synthetic_boundaries.json")
        del payload["elevation"]
        mock_forecast(payload)
        assert provider.hourly([DENVER], START, END)[0].elevation_m is None
