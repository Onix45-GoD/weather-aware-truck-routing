"""The response says what the router was asked to route for."""

from __future__ import annotations

import json

from django.test import Client


def test_request_echo_carries_gross_weight_and_kilograms(valid_payload, settings) -> None:
    settings.TRUCK_TARE_WEIGHT_LB = 35_000
    response = Client().post(
        "/api/v1/route-analysis", data=json.dumps(valid_payload), content_type="application/json"
    )
    assert response.status_code == 200
    echo = response.json()["request"]
    assert echo["load_weight_lb"] == 42_000
    assert echo["tare_weight_lb"] == 35_000
    assert echo["gross_weight_lb"] == 77_000
    assert echo["vehicle_weight_kg"] == 34_927  # 77,000 lb, rounded


def test_tare_follows_settings(valid_payload, settings) -> None:
    settings.TRUCK_TARE_WEIGHT_LB = 30_000
    echo = Client().post(
        "/api/v1/route-analysis", data=json.dumps(valid_payload), content_type="application/json"
    ).json()["request"]
    assert echo["gross_weight_lb"] == 72_000
