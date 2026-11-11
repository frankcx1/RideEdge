from datetime import datetime, timedelta

from farol.adapters.wsdot import _alert_time, parse_alerts


def test_dotnet_timestamp_offset_is_not_applied_twice():
    expected = datetime.fromisoformat("2026-09-17T21:00:00-07:00")
    raw = f"/Date({int(expected.timestamp() * 1000)}-0700)/"
    assert _alert_time(raw, expected.tzinfo) == expected
    assert _alert_time(expected.isoformat(), expected.tzinfo) == expected
    assert _alert_time("not a timestamp", expected.tzinfo) is None


def test_expired_and_future_dotnet_alerts_are_not_current_signals():
    now = datetime.fromisoformat("2026-09-17T21:00:00-07:00")

    def row(ident, start, end):
        return {"AlertID": ident, "Region": "Northwest", "Priority": "High",
                "StartRoadwayLocation": {"RoadName": "405", "MilePost": 16},
                "StartTime": f"/Date({int(start.timestamp() * 1000)}-0700)/",
                "EndTime": f"/Date({int(end.timestamp() * 1000)}-0700)/"}

    payload = [row(1, now - timedelta(hours=2), now - timedelta(hours=1)),
               row(2, now + timedelta(days=1), now + timedelta(days=2)),
               row(3, now, now + timedelta(hours=2))]
    signals = parse_alerts(payload, now, now + timedelta(hours=3), fetched_at=now.isoformat())
    assert signals
    assert all(signal.id.startswith("wsdot-alert-3-") for signal in signals)
