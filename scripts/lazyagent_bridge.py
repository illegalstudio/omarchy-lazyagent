#!/usr/bin/env python3
"""Bounded JSON bridge between the Omarchy QML plugin and lazyagent.

The plugin never shells out to lazyagent directly. This bridge locates the
executable, runs `lazyagent limits --json` with a fixed argument array and a
deadline, and re-emits a sanitised copy of the report so the QML side only
ever receives known keys with the expected types and bounded sizes.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


MAX_OUTPUT = 512 * 1024
MAX_REPORTS = 32
MAX_WINDOWS = 16
MAX_ERRORS = 16
LIMITS_TIMEOUT = 60
AGENTS = {"all", "claude", "codex", "grok", "kimi", "cursor"}
PACE_LABELS = {"underutilizing", "on track", "overutilizing", ""}
SEVERITIES = {"default", "ok", "info", "warn", "danger"}
ERROR_KINDS = {"not_installed", "unavailable", "error"}


def compact(text: str, limit: int = 600) -> str:
    value = " ".join((text or "").split())
    return value if len(value) <= limit else value[: limit - 3] + "..."


def emit(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0 if payload.get("ok") is not False else 1


def executable(path: str | Path | None) -> str | None:
    if not path:
        return None
    candidate = Path(path).expanduser()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        # Keep the invoked path intact: a mise shim dispatches from its
        # argv[0] name, and resolving the symlink would break that.
        return str(candidate.absolute())
    return None


def locate_mise() -> str | None:
    override = executable(os.environ.get("OMARCHY_LAZYAGENT_MISE"))
    return override or shutil.which("mise")


def locate_lazyagent() -> str | None:
    override = executable(os.environ.get("OMARCHY_LAZYAGENT_BIN"))
    if override:
        return override

    found = shutil.which("lazyagent")
    if found:
        return executable(found)

    mise = locate_mise()
    if mise:
        try:
            result = subprocess.run(
                [mise, "which", "lazyagent"],
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
            if result.returncode == 0:
                managed = executable(result.stdout.strip())
                if managed:
                    return managed
        except (OSError, subprocess.TimeoutExpired):
            pass

    home = Path.home()
    candidates = [
        home / ".local/bin/lazyagent",
        Path("/home/linuxbrew/.linuxbrew/bin/lazyagent"),
        home / ".linuxbrew/bin/lazyagent",
        Path("/usr/local/bin/lazyagent"),
    ]
    for candidate in candidates:
        managed = executable(candidate)
        if managed:
            return managed
    return None


def run_process(argv: list[str], timeout: int) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "exitCode": None, "stdout": "", "stderr": "",
                "error": "lazyagent timed out"}
    except OSError as error:
        return {"ok": False, "exitCode": None, "stdout": "", "stderr": "",
                "error": compact(str(error))}
    return {
        "ok": result.returncode == 0,
        "exitCode": result.returncode,
        "stdout": result.stdout[:MAX_OUTPUT],
        "stderr": result.stderr[:MAX_OUTPUT],
    }


def version_of(binary: str) -> str:
    result = run_process([binary, "--version"], timeout=5)
    return compact(result.get("stdout") or result.get("stderr") or "", 120)


def probe() -> dict[str, Any]:
    binary = locate_lazyagent()
    return {
        "ok": True,
        "installed": binary is not None,
        "path": binary or "",
        "version": version_of(binary) if binary else "",
    }


def as_number(value: Any, fallback: float = 0.0) -> float:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else fallback
    return fallback


def as_text(value: Any, limit: int = 240) -> str:
    return compact(value, limit) if isinstance(value, str) else ""


def as_enum(value: Any, allowed: set[str], fallback: str) -> str:
    return value if isinstance(value, str) and value in allowed else fallback


def sanitize_window(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    return {
        "label": as_text(raw.get("label"), 64) or "window",
        "window_minutes": int(max(0.0, as_number(raw.get("window_minutes")))),
        "used_percent": max(0.0, as_number(raw.get("used_percent"))),
        "expected_percent": max(0.0, as_number(raw.get("expected_percent"))),
        "pace_known": raw.get("pace_known") is True,
        "pace_ratio": max(0.0, as_number(raw.get("pace_ratio"))),
        "pace_label": as_enum(raw.get("pace_label"), PACE_LABELS, ""),
        "used_severity": as_enum(raw.get("used_severity"), SEVERITIES, "default"),
        "resets_at": as_text(raw.get("resets_at"), 64),
        "reset_in_seconds": int(max(0.0, as_number(raw.get("reset_in_seconds")))),
        "reset_relative": as_text(raw.get("reset_relative"), 32),
    }


def sanitize_cell(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    return {
        "used_percent": max(0.0, as_number(raw.get("used_percent"))),
        "expected_percent": max(0.0, as_number(raw.get("expected_percent"))),
        "severity": as_enum(raw.get("severity"), SEVERITIES, "default"),
        "text": as_text(raw.get("text"), 64),
    }


def sanitize_report(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    windows = []
    for item in raw.get("windows") or []:
        window = sanitize_window(item)
        if window:
            windows.append(window)
        if len(windows) >= MAX_WINDOWS:
            break
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    agent = as_text(raw.get("agent"), 32)
    provider = as_text(raw.get("provider"), 64)
    return {
        "agent": agent or "unknown",
        "provider": provider or agent or "Unknown",
        "short_name": as_text(raw.get("short_name"), 32) or provider or agent,
        "source": as_text(raw.get("source"), 400),
        "note": as_text(raw.get("note"), 600),
        "windows": windows,
        "summary": {
            "five_hour": sanitize_cell(summary.get("five_hour")),
            "week_global": sanitize_cell(summary.get("week_global")),
        },
    }


def sanitize_error(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    return {
        "agent": as_text(raw.get("agent"), 32) or "unknown",
        "kind": as_enum(raw.get("kind"), ERROR_KINDS, "error"),
        "message": as_text(raw.get("message"), 400),
    }


def sanitize_limits(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("reports"), list) or not isinstance(payload.get("errors"), list):
        return None
    reports = []
    for item in payload["reports"]:
        report = sanitize_report(item)
        if report:
            reports.append(report)
        if len(reports) >= MAX_REPORTS:
            break
    errors = []
    for item in payload["errors"]:
        error = sanitize_error(item)
        if error:
            errors.append(error)
        if len(errors) >= MAX_ERRORS:
            break
    return {
        "generatedAt": as_text(payload.get("generated_at"), 64),
        "reports": reports,
        "errors": errors,
    }


def snapshot(agent: str) -> dict[str, Any]:
    if agent not in AGENTS:
        return {"ok": False, "error": "Unsupported agent filter"}

    binary = locate_lazyagent()
    if not binary:
        return {
            "ok": True,
            "installed": False,
            "path": "",
            "version": "",
            "generatedAt": "",
            "reports": [],
            "errors": [],
        }

    argv = [binary, "limits", "--json"]
    if agent != "all":
        argv.extend(["--agent", agent])
    result = run_process(argv, timeout=LIMITS_TIMEOUT)

    base: dict[str, Any] = {
        "ok": True,
        "installed": True,
        "path": binary,
        "version": version_of(binary),
        "exitCode": result.get("exitCode"),
        "generatedAt": "",
        "reports": [],
        "errors": [],
    }

    if "error" in result:
        base["ok"] = False
        base["error"] = result["error"]
        return base

    # lazyagent exits 1 when any agent failed, but its JSON is still complete
    # and carries the failure in "errors". Parse stdout regardless of the
    # exit code and only give up when there is no usable document.
    source = (result.get("stdout") or "").strip()
    payload: Any = None
    if source:
        try:
            payload = json.loads(source)
        except json.JSONDecodeError:
            payload = None
    limits = sanitize_limits(payload)
    if limits is None:
        base["ok"] = False
        base["error"] = compact(
            result.get("stderr") or result.get("stdout") or "lazyagent returned invalid data",
            400,
        )
        return base

    base.update(limits)
    return base


def parse_agent(args: list[str]) -> tuple[str, list[str]]:
    if len(args) >= 2 and args[0] == "--agent":
        return args[1], args[2:]
    return "all", args


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in {"-h", "--help", "help"}:
        return emit({
            "ok": True,
            "usage": "lazyagent_bridge.py probe|snapshot [--agent NAME]",
        })

    command = argv[1]
    args = argv[2:]
    if command == "probe" and not args:
        return emit(probe())
    if command == "snapshot":
        agent, rest = parse_agent(args)
        if rest:
            return emit({"ok": False, "error": "Unexpected snapshot arguments"})
        return emit(snapshot(agent))
    return emit({"ok": False, "error": "Unknown bridge command"})


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except Exception as error:
        raise SystemExit(emit({"ok": False, "error": compact(str(error))}))
