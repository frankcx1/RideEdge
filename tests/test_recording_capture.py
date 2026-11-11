import json
from pathlib import Path
import pytest
from farol.recording_capture import load_capture, observe_inference, retain, seal


def test_text_is_only_retained_inside_explicit_context_and_copied():
    retain({"private": "not retained"}, {}, {})
    with observe_inference() as rows:
        request = {"messages": ["evidence"]}
        retain(request, {"actual": "answer"}, {"prompt_tokens": 17})
        request["messages"].clear()
        with observe_inference() as nested:
            retain({}, {}, {})
        assert len(nested) == len(rows) == 1
    retain({}, {}, {})
    assert len(rows) == 1
    assert rows[0]["request"]["messages"] == ["evidence"]


def test_capture_roundtrip_rejects_tampered_data_and_authored_fixture(tmp_path):
    base = Path(__file__).resolve().parents[1]
    radar = json.loads((base / "fixtures/contracts/radar-v1.json").read_text())
    package = seal({"kind": "captured_session", "schema_version": 1, "stages": [{"radar": radar}]})
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(package))
    assert load_capture(path)["stages"][0]["radar"] == radar
    package["stages"][0]["radar"]["snapshot_id"] = "changed"
    path.write_text(json.dumps(package))
    with pytest.raises(ValueError, match="checksum"):
        load_capture(path)
    path.write_text(json.dumps({"synthetic": True, "schema_version": 1}))
    with pytest.raises(ValueError, match="Not a captured"):
        load_capture(path)


def test_studio_missing_capture_never_falls_back_to_authored_data(tmp_path, monkeypatch):
    from farol import studio
    from fastapi import HTTPException
    monkeypatch.setattr(studio, "ROOT", tmp_path)
    with pytest.raises(HTTPException) as error:
        studio.studio_data(mode="captured")
    assert error.value.status_code == 409


def test_plan_inspection_flags_do_not_disable_shared_now_option():
    from farol.radar_contract import project
    from farol.radar import stamp
    base = Path(__file__).resolve().parents[1]
    scene = json.loads((base / "fixtures/contracts/recording-demo.json").read_text(encoding="utf-8"))["stages"][0]["radar"]
    selected = scene["now"][0]
    scene["plan"][0]["options"] = [selected]
    scene["plan"][0]["selected_id"] = selected["id"]
    result = project(scene, stamp(scene["server_time"]))
    assert result["now"][0]["actionable"]
    assert not result["plan"][0]["options"][0]["actionable"]
    assert selected["actionable"]  # no input mutation
