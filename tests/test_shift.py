import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from farol.brain import apply
from farol.local import narration_from_payload
from farol.shift import active, status


class ShiftLauncherTests(unittest.TestCase):
    def test_launcher_writes_to_files_instead_of_waiting_for_child_pipe_eof(self):
        from farol import shift

        def launcher(args, **kwargs):
            self.assertNotIn("capture_output", kwargs)
            self.assertNotEqual(kwargs["stdout"], shift.subprocess.PIPE)
            self.assertNotEqual(kwargs["stderr"], shift.subprocess.PIPE)
            kwargs["stdout"].write(b'launcher diagnostic\n{"ok":true,"phase":"driving"}\n')
            child = unittest.mock.Mock(pid=42)
            child.wait.return_value = 0
            child.poll.return_value = 0
            return child

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / "launcher.ps1"
            script.touch()
            with (
                patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}),
                patch.object(shift, "ROOT", root),
                patch.object(shift, "SCRIPT", script),
                patch.object(shift.subprocess, "Popen", side_effect=launcher),
                patch("farol.process_control.process_identity", return_value="fixture"),
                patch.object(shift, "_control", None),
            ):
                result = shift._run_script("start")
            self.assertTrue(result["ok"])
            self.assertEqual(result["phase"], "driving")
            self.assertEqual(len(list((root / ".cache" / "runtime").glob("*.log"))), 2)

    def test_launcher_preserves_failure_diagnostics(self):
        from farol import shift

        def launcher(args, **kwargs):
            kwargs["stderr"].write(b"synthetic launcher failure")
            child = unittest.mock.Mock(pid=42)
            child.wait.return_value = 12
            child.poll.return_value = 12
            return child

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / "launcher.ps1"
            script.touch()
            with (
                patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}),
                patch.object(shift, "ROOT", root),
                patch.object(shift, "SCRIPT", script),
                patch.object(shift.subprocess, "Popen", side_effect=launcher),
                patch("farol.process_control.process_identity", return_value="fixture"),
                patch.object(shift, "_control", None),
            ):
                result = shift._run_script("start")
            self.assertFalse(result["ok"])
            self.assertEqual(result["exit"], 12)
            self.assertIn("synthetic launcher failure", result["detail"])


class LocalNarrationTests(unittest.TestCase):
    def test_local_request_uses_schema_and_disables_thinking(self):
        from farol.local import NARRATION_SCHEMA, complete

        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"choices": []}'
        with patch("farol.local.urlopen", return_value=response) as request:
            complete(system="fixture", user="{}", cache_key="test", model_profile="gemma")
        body = json.loads(request.call_args.args[0].data)
        self.assertEqual(body["response_format"]["schema"], NARRATION_SCHEMA)
        self.assertFalse(body["chat_template_kwargs"]["enable_thinking"])

    def test_chat_completions_json_is_extracted(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"headline":"WAIT","spoken":"Stay on Rose Hill.","shift_rationale":"Engine 24 vs floor 22.","now_move":"WAIT","risks":[],"opportunity_notes":{}}'
                    }
                }
            ]
        }
        blob = narration_from_payload(payload)
        self.assertEqual(blob["headline"], "WAIT")
        self.assertIn("Rose Hill", blob["spoken"])


class ShiftFlagTests(unittest.TestCase):
    def test_pytest_does_not_read_a_stale_shift_file(self):
        self.assertFalse(active())

    def test_status_reads_shift_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shift.json"
            path.write_text(json.dumps({"phase": "driving", "model": "qwen3.8-27b"}), encoding="utf-8")
            with patch("farol.shift.STATE_PATH", path):
                self.assertEqual(status()["phase"], "driving")
                self.assertEqual(status()["model"], "qwen3.8-27b")


class LocalBrainApplyTests(unittest.TestCase):
    def test_changing_local_models_does_not_reuse_other_models_narration(self):
        from farol.tonight import tonight_brief

        keys = []
        for model in ("qwen3.8-27b", "gemma-4-26b-a4b"):
            brief = tonight_brief()
            brief["mock_feeds"] = False
            with (
                patch.dict(os.environ, {"FAROL_SHIFT_ACTIVE": "1", "FAROL_LOCAL_MODEL": model,
                                        "FAROL_BRAIN": "local"}),
                patch("farol.shift.status", return_value={"phase": "driving", "model": model}),
                patch("farol.brain.read_cache", return_value=None) as read,
                patch("farol.local.complete", side_effect=ValueError("synthetic no model")),
            ):
                apply(brief)
                keys.append(read.call_args.args[0])
        self.assertNotEqual(*keys)

    def test_shift_uses_local_complete_not_grok(self):
        from farol.tonight import tonight_brief

        engine = tonight_brief()
        live = dict(engine)
        live["mock_feeds"] = False
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "headline": "DRIVE",
                                "spoken": "Harvest Kirkland closer.",
                                "shift_rationale": "Engine clears your floor.",
                                "now_move": "WATCH Rose Hill",
                                "risks": ["405"],
                                "opportunity_notes": {},
                            }
                        )
                    }
                }
            ]
        }
        with (
            patch.dict(os.environ, {"FAROL_SHIFT_ACTIVE": "1", "FAROL_BRAIN": "grok"}),
            patch("farol.brain.read_cache", return_value=None),
            patch("farol.brain.write_cache", return_value="2026-09-06T20:00:00+00:00"),
            patch("farol.local.complete", return_value=(payload, "live", "2026-09-06T20:00:00+00:00")) as complete,
            patch("farol.grok.complete") as grok,
        ):
            result = apply(live)
        complete.assert_called_once()
        grok.assert_not_called()
        self.assertEqual(result["brain"]["provider"], "local")
        self.assertEqual(result["narration"]["now_move"], "WATCH")
        self.assertEqual(
            {item["id"]: item["score"] for item in result["opportunities"]},
            {item["id"]: item["score"] for item in engine["opportunities"]},
        )
