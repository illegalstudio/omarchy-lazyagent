from __future__ import annotations

import importlib.util
import io
import json
import os
from contextlib import redirect_stdout
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
log = os.environ.get("FAKE_LAZYAGENT_LOG")
if log:
    with open(log, "a") as handle:
        handle.write(" ".join(args) + "\n")
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
claude = {
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
        },
        {
            "label": "7-day",
            "scope": "Fable",
            "detail": "11% of the weekly limit used, capped at 50%",
            "window_minutes": 10080,
            "used_percent": 21,
            "expected_percent": 30,
            "pace_known": True,
            "pace_ratio": 0.7,
            "pace_label": "underutilizing",
            "used_severity": "ok",
            "resets_at": None,
            "reset_in_seconds": 0,
            "reset_relative": ""
        }
    ],
    "resets": [
        {"label": "New model launch: one Fable reset", "left": 1, "total": 1, "usable": True,
         "status": "", "expires_at": "2027-03-09T07:59:00Z", "expires_in_seconds": 10081971,
         "next_available_at": None, "next_available_in_seconds": 0,
         "text": "1 of 1 left · expires in 116d 16h (Tue 9 Mar 08:59 CET) · usable now"},
        {"label": 7, "left": "many", "total": -3, "usable": "yes", "status": None,
         "expires_in_seconds": -5, "next_available_in_seconds": True},
        "not a reset"
    ],
    "credits": [
        {"label": "Extra usage", "unit": "EUR", "enabled": False, "balance": None, "used": 0,
         "limit": None, "status": "set by your organization", "text": "disabled · set by your organization"},
        {"label": "Balance", "unit": "USD", "enabled": True, "balance": -2.5, "used": "lots",
         "limit": True, "status": "", "text": ""}
    ],
    "summary": {
        "five_hour": {"used_percent": 4, "expected_percent": 73.57, "severity": "ok", "text": "4.0% used / 73.6% exp"},
        "week_global": {"used_percent": 95, "expected_percent": 91.77, "severity": "danger", "text": "95.0% used / 91.8% exp"}
    }
}
codex = {
    "agent": "codex", "provider": "Codex", "short_name": "Codex", "source": "", "note": "",
    "windows": [{"label": "7-day", "window_minutes": 10080, "used_percent": 11, "expected_percent": 3.6,
                 "pace_known": True, "pace_ratio": 3.0, "pace_label": "overutilizing", "used_severity": "ok",
                 "resets_at": "2026-09-14T09:01:00+02:00", "reset_in_seconds": 582617, "reset_relative": "in 6d 17h"}],
    "summary": {"five_hour": None, "week_global": {"used_percent": 11, "expected_percent": 3.6, "severity": "danger", "text": ""}}
}
document = {
    "generated_at": "2026-09-07T15:10:42.421095089+02:00",
    "reports": [claude, codex, {"agent": "bogus", "provider": 12, "windows": "nope", "summary": None}, "not a report"],
    "errors": [
        {"agent": "kimi", "kind": "not_installed", "message": "Kimi Code CLI is not installed."},
        {"agent": "grok", "kind": "weird", "message": 5},
        42
    ]
}
if mode == "rate_limited":
    document["reports"] = [codex]
    document["errors"] = [
        {"agent": "kimi", "kind": "not_installed", "message": "Kimi Code CLI is not installed."},
        {"agent": "claude", "kind": "error", "message": "Claude usage endpoint rate-limited (429). Try again in a minute"},
    ]
if mode == "claude_down":
    document["reports"] = [codex]
    document["errors"] = [{"agent": "claude", "kind": "error", "message": "connection refused"}]
if agent != "all":
    document["reports"] = [r for r in document["reports"] if isinstance(r, dict) and r.get("agent") == agent]
    document["errors"] = [e for e in document["errors"] if isinstance(e, dict) and e.get("agent") == agent]
if mode == "windows_invalid":
    document["reports"][0]["windows"][0]["used_percent"] = "NaN"
    document["reports"][0]["windows"][0]["pace_label"] = "sideways"
print(json.dumps(document))
raise SystemExit(1 if mode in {"exit1", "rate_limited", "claude_down"} else 0)
'''


NOW = 1_800_000_000.0


class BridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.binary = root / "lazyagent"
        self.binary.write_text(FAKE_LAZYAGENT)
        self.binary.chmod(0o755)
        self.log = root / "calls.log"
        self.state = root / "state/limits.json"
        self.env = mock.patch.dict(
            os.environ,
            {
                "OMARCHY_LAZYAGENT_BIN": str(self.binary),
                "OMARCHY_LAZYAGENT_STATE": str(self.state),
                "FAKE_LAZYAGENT_LOG": str(self.log),
                "FAKE_LAZYAGENT_MODE": "ok",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def limits_calls(self) -> list[str]:
        if not self.log.exists():
            return []
        return [line for line in self.log.read_text().splitlines() if line.startswith("limits")]

    def set_mode(self, mode: str) -> None:
        os.environ["FAKE_LAZYAGENT_MODE"] = mode

    # ------------------------------------------------------------ discovery

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

    # ------------------------------------------------------------- snapshot

    def test_snapshot_sanitizes_reports_and_errors(self) -> None:
        result = BRIDGE.snapshot("all", now=NOW)
        self.assertTrue(result["ok"])
        self.assertTrue(result["installed"])
        self.assertFalse(result["fromCache"])
        self.assertEqual(result["fetchedAt"], NOW)
        self.assertEqual(result["backoffUntil"], 0.0)
        self.assertEqual(result["generatedAt"], "2026-09-07T15:10:42.421095089+02:00")

        self.assertEqual([r["agent"] for r in result["reports"]], ["claude", "codex", "bogus"])
        claude = result["reports"][0]
        self.assertEqual(claude["provider"], "Claude Code")
        self.assertEqual(len(claude["windows"]), 3)
        self.assertEqual(claude["windows"][0]["scope"], "")
        self.assertEqual(claude["windows"][0]["detail"], "")
        self.assertEqual(claude["windows"][2]["scope"], "Fable")
        self.assertEqual(claude["windows"][2]["detail"], "11% of the weekly limit used, capped at 50%")
        self.assertEqual(claude["windows"][0]["pace_label"], "underutilizing")
        self.assertEqual(claude["windows"][1]["used_severity"], "danger")
        self.assertEqual(claude["windows"][1]["resets_at"], "")
        self.assertEqual(claude["summary"]["week_global"]["severity"], "danger")
        self.assertEqual(claude["fetched_at"], NOW)
        self.assertFalse(claude["stale"])

        self.assertEqual(claude["resets"], [
            {"label": "New model launch: one Fable reset", "left": 1, "total": 1, "usable": True,
             "status": "", "expires_in_seconds": 10081971, "next_available_in_seconds": 0,
             "text": "1 of 1 left · expires in 116d 16h (Tue 9 Mar 08:59 CET) · usable now"},
            {"label": "Limit reset", "left": 0, "total": 0, "usable": False, "status": "",
             "expires_in_seconds": 0, "next_available_in_seconds": 0, "text": ""},
        ])
        self.assertEqual(claude["credits"][0]["balance"], None)
        self.assertEqual(claude["credits"][0]["used"], 0.0)
        self.assertFalse(claude["credits"][0]["enabled"])
        self.assertEqual(claude["credits"][0]["text"], "disabled · set by your organization")
        self.assertEqual(claude["credits"][1]["balance"], -2.5)
        self.assertIsNone(claude["credits"][1]["used"])
        self.assertIsNone(claude["credits"][1]["limit"])

        codex = result["reports"][1]
        self.assertEqual(codex["resets"], [])
        self.assertEqual(codex["credits"], [])

        bogus = result["reports"][2]
        self.assertEqual(bogus["provider"], "bogus")
        self.assertEqual(bogus["windows"], [])
        self.assertIsNone(bogus["summary"]["five_hour"])

        self.assertEqual(len(result["errors"]), 2)
        self.assertEqual(result["errors"][0]["kind"], "not_installed")
        self.assertFalse(result["errors"][0]["rate_limited"])
        self.assertEqual(result["errors"][1]["kind"], "error")
        self.assertEqual(result["errors"][1]["message"], "")

    def test_snapshot_keeps_data_when_lazyagent_exits_nonzero(self) -> None:
        self.set_mode("exit1")
        result = BRIDGE.snapshot("all", now=NOW)
        self.assertTrue(result["ok"])
        self.assertEqual(result["exitCode"], 1)
        self.assertEqual(len(result["reports"]), 3)

    def test_snapshot_passes_agent_filter(self) -> None:
        result = BRIDGE.snapshot("claude", now=NOW)
        self.assertTrue(result["ok"])
        self.assertEqual([r["agent"] for r in result["reports"]], ["claude"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(self.limits_calls(), ["limits --json --agent claude"])

    def test_snapshot_rejects_unknown_agent(self) -> None:
        result = BRIDGE.snapshot("shell; rm -rf /", now=NOW)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Unsupported agent filter")

    def test_snapshot_coerces_invalid_numbers_and_enums(self) -> None:
        self.set_mode("windows_invalid")
        result = BRIDGE.snapshot("all", now=NOW)
        window = result["reports"][0]["windows"][0]
        self.assertEqual(window["used_percent"], 0.0)
        self.assertEqual(window["pace_label"], "")

    def test_snapshot_reports_invalid_output(self) -> None:
        self.set_mode("garbage")
        result = BRIDGE.snapshot("all", now=NOW)
        self.assertFalse(result["ok"])
        self.assertTrue(result["installed"])
        self.assertIn("not json", result["error"])
        self.assertEqual(result["reports"], [])
        self.assertFalse(self.state.exists())

    def test_snapshot_reports_timeout(self) -> None:
        self.set_mode("hang")
        with mock.patch.object(BRIDGE, "LIMITS_TIMEOUT", 1):
            result = BRIDGE.snapshot("all", now=NOW)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "lazyagent timed out")

    def test_snapshot_without_binary(self) -> None:
        with mock.patch.object(BRIDGE, "locate_lazyagent", return_value=None):
            result = BRIDGE.snapshot("all", now=NOW)
        self.assertTrue(result["ok"])
        self.assertFalse(result["installed"])
        self.assertEqual(result["reports"], [])
        self.assertEqual(result["backoffUntil"], 0.0)

    # ---------------------------------------------------------------- cache

    def test_snapshot_serves_fresh_cache_without_calling_lazyagent(self) -> None:
        first = BRIDGE.snapshot("all", now=NOW)
        self.assertTrue(self.state.exists())
        second = BRIDGE.snapshot("all", max_age=300, now=NOW + 100)
        self.assertTrue(second["fromCache"])
        self.assertEqual(second["fetchedAt"], NOW)
        self.assertEqual([r["agent"] for r in second["reports"]],
                         [r["agent"] for r in first["reports"]])
        self.assertEqual(second["reports"][0]["windows"][0]["reset_in_seconds"], 4757)
        self.assertEqual(len(self.limits_calls()), 1)

    def test_snapshot_refreshes_when_cache_is_older_than_max_age(self) -> None:
        BRIDGE.snapshot("all", now=NOW)
        result = BRIDGE.snapshot("all", max_age=300, now=NOW + 301)
        self.assertFalse(result["fromCache"])
        self.assertEqual(result["fetchedAt"], NOW + 301)
        self.assertEqual(len(self.limits_calls()), 2)

    def test_snapshot_ignores_cache_for_a_different_agent_filter(self) -> None:
        BRIDGE.snapshot("all", now=NOW)
        result = BRIDGE.snapshot("claude", max_age=300, now=NOW + 10)
        self.assertFalse(result["fromCache"])
        self.assertEqual([r["agent"] for r in result["reports"]], ["claude"])

    def test_snapshot_force_bypasses_fresh_cache(self) -> None:
        BRIDGE.snapshot("all", now=NOW)
        result = BRIDGE.snapshot("all", force=True, max_age=300, now=NOW + 10)
        self.assertFalse(result["fromCache"])
        self.assertEqual(len(self.limits_calls()), 2)

    def test_corrupt_state_file_is_ignored(self) -> None:
        self.state.parent.mkdir(parents=True)
        self.state.write_text("{not json")
        result = BRIDGE.snapshot("all", max_age=300, now=NOW)
        self.assertTrue(result["ok"])
        self.assertFalse(result["fromCache"])
        self.state.write_text(json.dumps({"version": 99, "reports": "x"}))
        self.assertEqual(BRIDGE.load_state(), {})

    # -------------------------------------------------------------- backoff

    def test_rate_limit_sets_backoff_and_keeps_stale_report(self) -> None:
        BRIDGE.snapshot("all", now=NOW)
        self.set_mode("rate_limited")
        result = BRIDGE.snapshot("all", force=True, now=NOW + 60)
        self.assertTrue(result["ok"])
        self.assertEqual(result["backoffLevel"], 1)
        self.assertEqual(result["backoffUntil"], NOW + 60 + 120)
        self.assertIn("claude", result["backoffReason"])

        by_agent = {r["agent"]: r for r in result["reports"]}
        self.assertIn("claude", by_agent)
        self.assertTrue(by_agent["claude"]["stale"])
        self.assertEqual(by_agent["claude"]["fetched_at"], NOW)
        # Resets, credits and scoped windows survive the state file round-trip.
        self.assertEqual(len(by_agent["claude"]["resets"]), 2)
        self.assertIsNone(by_agent["claude"]["credits"][0]["balance"])
        self.assertEqual(by_agent["claude"]["windows"][2]["scope"], "Fable")
        self.assertFalse(by_agent["codex"]["stale"])
        self.assertEqual(by_agent["codex"]["fetched_at"], NOW + 60)
        self.assertEqual([r["agent"] for r in result["reports"]], ["claude", "codex"])

        limited = [e for e in result["errors"] if e["rate_limited"]]
        self.assertEqual([e["agent"] for e in limited], ["claude"])

    def test_backoff_serves_cache_until_it_expires_and_escalates(self) -> None:
        self.set_mode("rate_limited")
        BRIDGE.snapshot("all", now=NOW)
        calls = len(self.limits_calls())

        during = BRIDGE.snapshot("all", now=NOW + 30)
        self.assertTrue(during["fromCache"])
        self.assertEqual(during["backoffUntil"], NOW + 120)
        self.assertEqual(len(self.limits_calls()), calls)

        after = BRIDGE.snapshot("all", now=NOW + 121)
        self.assertFalse(after["fromCache"])
        self.assertEqual(after["backoffLevel"], 2)
        self.assertEqual(after["backoffUntil"], NOW + 121 + 240)

        again = BRIDGE.snapshot("all", now=NOW + 121 + 241)
        self.assertEqual(again["backoffLevel"], 3)
        self.assertEqual(again["backoffUntil"], NOW + 121 + 241 + 480)

    def test_backoff_delay_is_capped(self) -> None:
        backoff = {"until": 0.0, "level": 0, "reason": ""}
        delays = []
        now = NOW
        for _ in range(12):
            backoff = BRIDGE.next_backoff(backoff, now, "rate limited: claude")
            delays.append(backoff["until"] - now)
        self.assertEqual(delays[:4], [120, 240, 480, 960])
        self.assertEqual(delays[-1], 1800)
        self.assertEqual(backoff["level"], BRIDGE.BACKOFF_MAX_LEVEL)

    def test_backoff_clears_after_a_clean_snapshot(self) -> None:
        self.set_mode("rate_limited")
        BRIDGE.snapshot("all", now=NOW)
        self.set_mode("ok")
        result = BRIDGE.snapshot("all", force=True, now=NOW + 10)
        self.assertEqual(result["backoffLevel"], 0)
        self.assertEqual(result["backoffUntil"], 0.0)
        self.assertFalse(any(r["stale"] for r in result["reports"]))

    def test_generic_failure_shows_stale_report_without_backoff(self) -> None:
        BRIDGE.snapshot("all", now=NOW)
        self.set_mode("claude_down")
        result = BRIDGE.snapshot("all", force=True, now=NOW + 10)
        self.assertEqual(result["backoffLevel"], 0)
        by_agent = {r["agent"]: r for r in result["reports"]}
        self.assertTrue(by_agent["claude"]["stale"])
        self.assertFalse(result["errors"][0]["rate_limited"])

    def test_stale_reports_expire(self) -> None:
        BRIDGE.snapshot("all", now=NOW)
        self.set_mode("claude_down")
        result = BRIDGE.snapshot("all", force=True, now=NOW + BRIDGE.STALE_MAX_AGE_SECONDS + 1)
        self.assertEqual([r["agent"] for r in result["reports"]], ["codex"])

    def test_total_failure_returns_stale_cache(self) -> None:
        BRIDGE.snapshot("all", now=NOW)
        self.set_mode("garbage")
        result = BRIDGE.snapshot("all", force=True, now=NOW + 10)
        self.assertFalse(result["ok"])
        self.assertTrue(result["fromCache"])
        self.assertTrue(all(r["stale"] for r in result["reports"]))
        self.assertEqual([r["agent"] for r in result["reports"]], ["claude", "codex"])
        self.assertEqual(result["fetchedAt"], NOW)

    # ------------------------------------------------------------------ cli

    def run_main(self, args: list[str]) -> tuple[int, dict]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = BRIDGE.main(["bridge"] + args)
        return code, json.loads(buffer.getvalue())

    def test_main_snapshot_emits_json(self) -> None:
        code, payload = self.run_main(["snapshot", "--agent", "claude"])
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reports"][0]["agent"], "claude")

    def test_main_parses_force_and_max_age(self) -> None:
        self.run_main(["snapshot"])
        code, payload = self.run_main(["snapshot", "--max-age", "3600"])
        self.assertEqual(code, 0)
        self.assertTrue(payload["fromCache"])
        code, payload = self.run_main(["snapshot", "--force", "--max-age", "3600"])
        self.assertFalse(payload["fromCache"])

    def test_main_rejects_bad_arguments(self) -> None:
        code, payload = self.run_main(["snapshot", "extra"])
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        code, payload = self.run_main(["snapshot", "--max-age", "-5"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "Invalid --max-age value")


if __name__ == "__main__":
    unittest.main()
