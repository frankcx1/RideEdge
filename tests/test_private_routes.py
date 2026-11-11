"""Exercise the real adapter/cache writer using a fake HTTP transport, no provider spend."""
import json
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from farol.adapters import base, routes
from farol.signals import Anchor

ORIGIN = (47.611234, -122.331234)  # Synthetic fixture, not a device observation.
ANCHORS = [Anchor("fixture-venue", "fixture-zone", "Fixture venue", 47.62, -122.32,
                  "MOVE", "demo_only", "Synthetic")]


def test_device_matrix_uses_real_memory_writer_without_disk_or_history(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "synthetic-not-a-real-key")
    monkeypatch.setenv("FAROL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(routes, "_private_cache", base.MemoryCache(900))
    response = MagicMock()
    # Include an echoed coordinate so even payload storage would expose the defect.
    payload = [{"destinationIndex": 0, "duration": "600s", "distanceMeters": 3000,
                "echo_origin": ORIGIN}]
    response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    with patch.object(base, "urlopen", return_value=response) as http, \
         patch.object(base, "write_cache", wraps=base.write_cache) as disk, \
         patch("farol.changes.retain_routes") as history:
        first, status = routes.matrix("fixture-device", *ORIGIN, ANCHORS, .45, "fixture")
        second, cached = routes.matrix("fixture-device", *ORIGIN, ANCHORS, .45, "fixture")
    assert first == second and first["fixture-venue"].traffic_minutes == 10
    assert status.mode == "live" and cached.mode == "cache"
    assert http.call_count == 1
    sent = json.loads(http.call_args.args[0].data)
    assert sent["origins"][0]["waypoint"]["location"]["latLng"]["latitude"] == ORIGIN[0]
    disk.assert_not_called()
    history.assert_not_called()
    assert not list(tmp_path.rglob("*"))


def test_public_place_cache_still_exercises_disk_writer(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "synthetic-not-a-real-key")
    monkeypatch.setenv("FAROL_CACHE_DIR", str(tmp_path))
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'[{"duration":"60s","distanceMeters":10}]'
    with patch.object(base, "urlopen", return_value=response), \
         patch.object(base, "write_cache", wraps=base.write_cache) as disk, \
         patch("farol.changes.retain_routes") as history:
        result, status = routes.matrix("fixture-public", *ORIGIN, ANCHORS, .45, "fixture",
                                      public_origin=True)
    assert result and status.mode == "live"
    disk.assert_called_once()
    history.assert_called()
    saved = list(tmp_path.glob("routes_matrix_*.json"))
    assert len(saved) == 1 and json.loads(saved[0].read_text())["payload"]


def test_private_provider_failure_does_not_surface_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "synthetic-not-a-real-key")
    monkeypatch.setenv("FAROL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(routes, "_private_cache", base.MemoryCache(900))
    with patch.object(base, "urlopen", side_effect=URLError(str(ORIGIN))):
        result, status = routes.matrix("fixture-device", *ORIGIN, ANCHORS, .45, "fixture")
    assert not result and status.mode == "error"
    assert all(str(c) not in status.detail for c in ORIGIN)
    assert not list(tmp_path.rglob("*"))


def test_memory_retention_is_bounded_expires_and_does_not_alias():
    cache = base.MemoryCache(10, capacity=2)
    with patch.object(base.time, "monotonic", return_value=100):
        cache.write("a", {"value": 1})
        cache.write("b", [])
        cache.read("a")["payload"]["value"] = 99
        assert cache.read("a")["payload"]["value"] == 1
        cache.write("c", [])
        assert cache.read("a") is None
    with patch.object(base.time, "monotonic", return_value=110):
        assert cache.read("b") is None and cache.read("c") is None
        assert not cache._entries
