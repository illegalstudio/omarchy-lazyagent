from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


BRIDGE_PATH = Path(__file__).parents[1] / "scripts/lazyagent_bridge.py"
SPEC = importlib.util.spec_from_file_location("lazyagent_bridge", BRIDGE_PATH)
BRIDGE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(BRIDGE)


FAKE_LAZYAGENT = r'''#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
if args == ["--version"]:
    print("lazyagent v9.9.9 (abcdef0)")
    raise SystemExit(0)

mode = os.environ.get("FAKE_LAZYAGENT_MODE", "ok")
if args[:2] != ["limits", "--json"]:
    print("unexpected arguments", file=sys.stderr)
    raise SystemExit(2)

if mode == "garbage":
    print("not json at all")
    raise SystemExit(0)
if mode == "hang":
    import time
    time.sleep(30)

agent = args[3] if len(args) >= 4 and args[2] == "--agent" else "all"
document = {
    "generated_at": "2026-09-07T15:10:42.421095089+02:00",
    "reports": [
        {
            "agent": "claude",
            "provider": "Claude Code",
            "short_name": "Claude",
            "source": "",
            "note": "Note: undocumented endpoint.",
            "windows": [
                {
                    "label": "5-hour",
                    "window_minutes": 300,
                    "used_percent": 4,
                    "expected_percent": 73.57,
                    "pace_known": True,
                    "pace_ratio": 0.054,
                    "pace_label": "underutilizing",
                    "used_severity": "ok",
                    "resets_at": "2026-09-07T14:29:59.716683Z",
                    "reset_in_seconds": 4757,
                    "reset_relative": "in 1h 19m"
                },
                {
                    "label": "7-day",
                    "window_minutes": 10080,
                    "used_percent": 95,
                    "expected_percent": 91.77,
                    "pace_known": True,
                    "pace_ratio": 1.03,
                    "pace_label": "on track",
                    "used_severity": "danger",
                    "resets_at": None,
                    "reset_in_seconds": 0,
                    "reset_relative": ""
                }
            ],
            "summary": {
                "five_hour": {"used_percent": 4, "expected_percent": 73.57, "severity": "ok", "text": "4.0% used / 73.6% exp"},
                "week_global": {"used_percent": 95, "expected_percent": 91.77, "severity": "danger", "text": "95.0% used / 91.8% exp"}
            }
        },
        {"agent": "bogus", "provider": 12, "windows": "nope", "summary": None},
        "not a report"
    ],
    "errors": [
        {"agent": "kimi", "kind": "not_installed", "message": "Kimi Code CLI is not installed."},
        {"agent": "grok", "kind": "weird", "message": 5},
        42
    ]
}
if agent != "all":
    document["reports"] = [r for r in document["reports"] if isinstance(r, dict) and r.get("agent") == agent]
    document["errors"] = []
if mode == "windows_invalid":
    document["reports"][0]["windows"][0]["used_percent"] = "NaN"
    document["reports"][0]["windows"][0]["pace_label"] = "sideways"
print(json.dumps(document))
raise SystemExit(1 if mode == "exit1" else 0)
'''


class BridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.binary = Path(self.temp_dir.name) / "lazyagent"
        self.binary.write_text(FAKE_LAZYAGENT)
        self.binary.chmod(0o755)
        self.env = mock.patch.dict(
            os.environ,
            {"OMARCHY_LAZYAGENT_BIN": str(self.binary), "FAKE_LAZYAGENT_MODE": "ok"},
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def test_probe_finds_explicit_binary(self) -> None:
        result = BRIDGE.probe()
        self.assertTrue(result["installed"])
        self.assertEqual(result["path"], str(self.binary))
        self.assertEqual(result["version"], "lazyagent v9.9.9 (abcdef0)")

    def test_probe_reports_missing_binary(self) -> None:
        with mock.patch.dict(os.environ, {"OMARCHY_LAZYAGENT_BIN": "/nonexistent/lazyagent"}):
            with mock.patch.object(BRIDGE.shutil, "which", return_value=None):
                with mock.patch.object(BRIDGE, "locate_mise", return_value=None):
                    with mock.patch.object(BRIDGE.Path, "home", return_value=Path(self.temp_dir.name)):
                        result = BRIDGE.probe()
        self.assertFalse(result["installed"])
        self.assertEqual(result["path"], "")

    def test_executable_preserves_a_shim_path(self) -> None:
        shim = Path(self.temp_dir.name) / "lazyagent-shim"
        shim.symlink_to(self.binary)
        self.assertEqual(BRIDGE.executable(shim), str(shim.absolute()))

    def test_snapshot_sanitizes_reports_and_errors(self) -> None:
        result = BRIDGE.snapshot("all")
        self.assertTrue(result["ok"])
        self.assertTrue(result["installed"])
        self.assertEqual(result["generatedAt"], "2026-09-07T15:10:42.421095089+02:00")

        self.assertEqual([r["agent"] for r in result["reports"]], ["claude", "bogus"])
        claude = result["reports"][0]
        self.assertEqual(claude["provider"], "Claude Code")
        self.assertEqual(len(claude["windows"]), 2)
        self.assertEqual(claude["windows"][0]["pace_label"], "underutilizing")
        self.assertEqual(claude["windows"][1]["used_severity"], "danger")
        self.assertEqual(claude["windows"][1]["resets_at"], "")
        self.assertEqual(claude["summary"]["week_global"]["severity"], "danger")

        bogus = result["reports"][1]
        self.assertEqual(bogus["provider"], "bogus")
        self.assertEqual(bogus["windows"], [])
        self.assertIsNone(bogus["summary"]["five_hour"])

        self.assertEqual(len(result["errors"]), 2)
        self.assertEqual(result["errors"][0]["kind"], "not_installed")
        self.assertEqual(result["errors"][1]["kind"], "error")
        self.assertEqual(result["errors"][1]["message"], "")

    def test_snapshot_keeps_data_when_lazyagent_exits_nonzero(self) -> None:
        with mock.patch.dict(os.environ, {"FAKE_LAZYAGENT_MODE": "exit1"}):
            result = BRIDGE.snapshot("all")
        self.assertTrue(result["ok"])
        self.assertEqual(result["exitCode"], 1)
        self.assertEqual(len(result["reports"]), 2)

    def test_snapshot_passes_agent_filter(self) -> None:
        result = BRIDGE.snapshot("claude")
        self.assertTrue(result["ok"])
        self.assertEqual([r["agent"] for r in result["reports"]], ["claude"])
        self.assertEqual(result["errors"], [])

    def test_snapshot_rejects_unknown_agent(self) -> None:
        result = BRIDGE.snapshot("shell; rm -rf /")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Unsupported agent filter")

    def test_snapshot_coerces_invalid_numbers_and_enums(self) -> None:
        with mock.patch.dict(os.environ, {"FAKE_LAZYAGENT_MODE": "windows_invalid"}):
            result = BRIDGE.snapshot("all")
        window = result["reports"][0]["windows"][0]
        self.assertEqual(window["used_percent"], 0.0)
        self.assertEqual(window["pace_label"], "")

    def test_snapshot_reports_invalid_output(self) -> None:
        with mock.patch.dict(os.environ, {"FAKE_LAZYAGENT_MODE": "garbage"}):
            result = BRIDGE.snapshot("all")
        self.assertFalse(result["ok"])
        self.assertTrue(result["installed"])
        self.assertIn("not json", result["error"])

    def test_snapshot_reports_timeout(self) -> None:
        with mock.patch.dict(os.environ, {"FAKE_LAZYAGENT_MODE": "hang"}):
            with mock.patch.object(BRIDGE, "LIMITS_TIMEOUT", 1):
                result = BRIDGE.snapshot("all")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "lazyagent timed out")

    def test_snapshot_without_binary(self) -> None:
        with mock.patch.object(BRIDGE, "locate_lazyagent", return_value=None):
            result = BRIDGE.snapshot("all")
        self.assertTrue(result["ok"])
        self.assertFalse(result["installed"])
        self.assertEqual(result["reports"], [])

    def test_main_snapshot_emits_json(self) -> None:
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = BRIDGE.main(["bridge", "snapshot", "--agent", "claude"])
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reports"][0]["agent"], "claude")

    def test_main_rejects_extra_arguments(self) -> None:
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = BRIDGE.main(["bridge", "snapshot", "extra"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(buffer.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
