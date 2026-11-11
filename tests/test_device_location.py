from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from farol.api import app


def test_working_device_pin_resolves_seattle_without_returning_coordinates():
    with patch("farol.here.load_observed_trips", return_value=[]), patch(
        "farol.here.score_window", return_value={"opportunities": [], "feeds": []}
    ):
        response = TestClient(app).post("/api/here", json={
            "latitude": 47.6062, "longitude": -122.3321})
    assert response.status_code == 200
    assert response.json()["place"]["zone"] == "seattle_core"
    assert response.json()["query"] == "Device location"
    assert response.json()["place"]["matched"] == "device location"
    assert response.headers["cache-control"] == "no-store"
    assert "47.6062" not in response.text and "-122.3321" not in response.text


@pytest.mark.parametrize("endpoint", ["/api/here", "/api/awareness"])
@pytest.mark.parametrize("pin", [
    {"latitude": 0, "longitude": 0},
    {"latitude": "nan", "longitude": -122.3321},
    {"latitude": 47.6062, "longitude": "Infinity"},
    {"latitude": 48.9, "longitude": -122.3321},
])
def test_invalid_pins_do_not_fall_back_to_kirkland(endpoint, pin):
    with patch("farol.here.score_window", side_effect=AssertionError("invalid pin")):
        assert TestClient(app).post(endpoint, json=pin).status_code == 400


def test_shared_location_asset_is_available():
    response = TestClient(app).get("/location.js")
    assert response.status_code == 200
    assert "enableHighAccuracy:true" in response.text
