#!/usr/bin/env python3
"""Bounded JSON bridge between the Omarchy QML plugin and lazyagent.

The plugin never shells out to lazyagent directly. This bridge locates the
executable, runs `lazyagent limits --json` with a fixed argument array and a
deadline, and re-emits a sanitised copy of the report so the QML side only
ever receives known keys with the expected types and bounded sizes.

It also owns a small state file so that the plugin behaves well towards the
undocumented provider endpoints lazyagent reads from:

- the last snapshot is cached, and automatic refreshes (shell start, timer,
  panel open) are served from it while it is younger than the caller's
  `--max-age`, so a shell restart does not trigger a new provider call;
- when a provider answers with a rate limit, an exponential backoff is
  recorded and every non-forced refresh is served from the cache until it
  expires, across shell restarts;
- the last good report of every agent is kept, and an agent that fails is
  shown with that report flagged as stale rather than disappearing.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any


MAX_OUTPUT = 512 * 1024
MAX_REPORTS = 32
MAX_WINDOWS = 16
MAX_ERRORS = 16
MAX_RESETS = 16
MAX_CREDITS = 8
LIMITS_TIMEOUT = 60
STATE_VERSION = 1
BACKOFF_BASE_SECONDS = 120
BACKOFF_CAP_SECONDS = 1800
BACKOFF_MAX_LEVEL = 8
STALE_MAX_AGE_SECONDS = 3 * 86400
AGENTS = {"all", "claude", "codex", "grok", "kimi", "cursor"}
AGENT_ORDER = ["claude", "codex", "grok", "kimi", "cursor"]
PACE_LABELS = {"underutilizing", "on track", "overutilizing", ""}
SEVERITIES = {"default", "ok", "info", "warn", "danger"}
ERROR_KINDS = {"not_installed", "unavailable", "error"}
RATE_LIMIT = re.compile(r"\b429\b|rate[ -]?limit|too many requests", re.IGNORECASE)


def compact(text: str, limit: int = 600) -> str:
    value = " ".join((text or "").split())
    return value if len(value) <= limit else value[: limit - 3] + "..."


def emit(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0 if payload.get("ok") is not False else 1


# --------------------------------------------------------------- discovery


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


# ------------------------------------------------------------ sanitising


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
        "scope": as_text(raw.get("scope"), 64),
        "detail": as_text(raw.get("detail"), 240),
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


def as_amount(value: Any) -> float | None:
    """A credit amount, or None when lazyagent says the provider did not
    report it. Unlike percentages, amounts may legitimately be negative."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def sanitize_reset(raw: Any) -> dict[str, Any] | None:
    """A banked limit reset. Only the countdowns are kept, not the absolute
    instants: the panel ticks them from the report's fetch time, like the
    window resets."""
    if not isinstance(raw, dict):
        return None
    return {
        "label": as_text(raw.get("label"), 160) or "Limit reset",
        "left": int(max(0.0, as_number(raw.get("left")))),
        "total": int(max(0.0, as_number(raw.get("total")))),
        "usable": raw.get("usable") is True,
        "status": as_text(raw.get("status"), 120),
        "expires_in_seconds": int(max(0.0, as_number(raw.get("expires_in_seconds")))),
        "next_available_in_seconds": int(max(0.0, as_number(raw.get("next_available_in_seconds")))),
        "text": as_text(raw.get("text"), 240),
    }


def sanitize_credit(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    return {
        "label": as_text(raw.get("label"), 64) or "Credits",
        "unit": as_text(raw.get("unit"), 16),
        "enabled": raw.get("enabled") is True,
        "balance": as_amount(raw.get("balance")),
        "used": as_amount(raw.get("used")),
        "limit": as_amount(raw.get("limit")),
        "status": as_text(raw.get("status"), 160),
        "text": as_text(raw.get("text"), 240),
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
    """Sanitise one report. Also accepts the two fields this bridge adds
    (`fetched_at`, `stale`) so cached reports round-trip through here."""
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
        "resets": sanitize_list(raw.get("resets"), sanitize_reset, MAX_RESETS),
        "credits": sanitize_list(raw.get("credits"), sanitize_credit, MAX_CREDITS),
        "summary": {
            "five_hour": sanitize_cell(summary.get("five_hour")),
            "week_global": sanitize_cell(summary.get("week_global")),
        },
        "fetched_at": max(0.0, as_number(raw.get("fetched_at"))),
        "stale": raw.get("stale") is True,
    }


def sanitize_error(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = as_enum(raw.get("kind"), ERROR_KINDS, "error")
    message = as_text(raw.get("message"), 400)
    return {
        "agent": as_text(raw.get("agent"), 32) or "unknown",
        "kind": kind,
        "message": message,
        "rate_limited": kind == "error" and bool(RATE_LIMIT.search(message)),
    }


def sanitize_list(items: Any, sanitizer: Any, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return result
    for item in items:
        clean = sanitizer(item)
        if clean:
            result.append(clean)
        if len(result) >= limit:
            break
    return result


def sanitize_limits(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("reports"), list) or not isinstance(payload.get("errors"), list):
        return None
    return {
        "generatedAt": as_text(payload.get("generated_at"), 64),
        "reports": sanitize_list(payload["reports"], sanitize_report, MAX_REPORTS),
        "errors": sanitize_list(payload["errors"], sanitize_error, MAX_ERRORS),
    }


def sanitize_backoff(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"until": 0.0, "level": 0, "reason": ""}
    return {
        "until": max(0.0, as_number(raw.get("until"))),
        "level": int(min(BACKOFF_MAX_LEVEL, max(0.0, as_number(raw.get("level"))))),
        "reason": as_text(raw.get("reason"), 120),
    }


def sort_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group by lazyagent's agent order; the sort is stable, so the pools of
    one agent (Cursor Models, then Cursor API) keep the order lazyagent gave."""
    def key(report: dict[str, Any]) -> int:
        agent = str(report.get("agent", ""))
        return AGENT_ORDER.index(agent) if agent in AGENT_ORDER else len(AGENT_ORDER)
    return sorted(reports, key=key)


# ------------------------------------------------------------------ state


def state_path() -> Path:
    override = os.environ.get("OMARCHY_LAZYAGENT_STATE")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    return base / "omarchy-lazyagent/limits.json"


def load_state() -> dict[str, Any]:
    """Read the state file, sanitising everything: it is our own file, but a
    corrupt or hand-edited one must not be able to break the panel."""
    try:
        raw = state_path().read_text(encoding="utf-8")
        if len(raw) > MAX_OUTPUT:
            return {}
        data = json.loads(raw)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return {}
    return {
        "agent": as_enum(data.get("agent"), AGENTS, ""),
        "fetchedAt": max(0.0, as_number(data.get("fetchedAt"))),
        "path": as_text(data.get("path"), 400),
        "versionText": as_text(data.get("versionText"), 120),
        "generatedAt": as_text(data.get("generatedAt"), 64),
        "reports": sanitize_list(data.get("reports"), sanitize_report, MAX_REPORTS),
        "errors": sanitize_list(data.get("errors"), sanitize_error, MAX_ERRORS),
        "backoff": sanitize_backoff(data.get("backoff")),
        "lastGood": sanitize_list(data.get("lastGood"), sanitize_report, MAX_REPORTS),
    }


def save_state(state: dict[str, Any]) -> None:
    path = state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps({"version": STATE_VERSION, **state}, ensure_ascii=False,
                       separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError:
        # A read-only or missing state directory only costs the cache.
        pass


def next_backoff(previous: dict[str, Any], now: float, reason: str) -> dict[str, Any]:
    level = min(BACKOFF_MAX_LEVEL, int(previous.get("level", 0)) + 1)
    delay = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** (level - 1)))
    return {"until": now + delay, "level": level, "reason": compact(reason, 120)}


def payload_from(
    state: dict[str, Any],
    backoff: dict[str, Any],
    from_cache: bool,
    installed: bool = True,
) -> dict[str, Any]:
    return {
        "ok": True,
        "installed": installed,
        "path": state.get("path", ""),
        "version": state.get("versionText", ""),
        "generatedAt": state.get("generatedAt", ""),
        "reports": sort_reports(state.get("reports", [])),
        "errors": state.get("errors", []),
        "fetchedAt": state.get("fetchedAt", 0.0),
        "fromCache": from_cache,
        "backoffUntil": backoff["until"],
        "backoffLevel": backoff["level"],
        "backoffReason": backoff["reason"],
    }


def stale_copies(reports: list[dict[str, Any]], agents: set[str], now: float) -> list[dict[str, Any]]:
    copies = []
    for report in reports:
        if report.get("agent") not in agents:
            continue
        if now - float(report.get("fetched_at", 0.0)) > STALE_MAX_AGE_SECONDS:
            continue
        copies.append({**report, "stale": True})
    return copies


# --------------------------------------------------------------- snapshot


def snapshot(agent: str, force: bool = False, max_age: float = 0.0,
             now: float | None = None) -> dict[str, Any]:
    if agent not in AGENTS:
        return {"ok": False, "error": "Unsupported agent filter"}
    now = time.time() if now is None else now

    binary = locate_lazyagent()
    if not binary:
        empty = {"path": "", "versionText": "", "generatedAt": "", "reports": [],
                 "errors": [], "fetchedAt": 0.0}
        return payload_from(empty, sanitize_backoff(None), False, installed=False)

    state = load_state()
    backoff = state.get("backoff", sanitize_backoff(None))
    if backoff["until"] <= now:
        # An expired backoff keeps its level so a fresh rate limit right
        # after it escalates instead of restarting from the shortest delay.
        backoff = {"until": 0.0, "level": backoff["level"], "reason": ""}
    cached = state if state.get("agent") == agent and state.get("fetchedAt", 0.0) > 0 else None
    cache_age = now - state["fetchedAt"] if cached else math.inf

    if not force and cached and (backoff["until"] > now or cache_age < max_age):
        return payload_from(cached, backoff, True)

    argv = [binary, "limits", "--json"]
    if agent != "all":
        argv.extend(["--agent", agent])
    result = run_process(argv, timeout=LIMITS_TIMEOUT)
    version = version_of(binary)

    # lazyagent exits 1 when any agent failed, but its JSON is still complete
    # and carries the failure in "errors". Parse stdout regardless of the
    # exit code and only give up when there is no usable document.
    limits = None
    if "error" not in result:
        source = (result.get("stdout") or "").strip()
        try:
            limits = sanitize_limits(json.loads(source)) if source else None
        except ValueError:
            limits = None

    if limits is None:
        failure = payload_from({
            "path": binary,
            "versionText": version,
            "generatedAt": state.get("generatedAt", ""),
            "reports": stale_copies(state.get("lastGood", []),
                                    set(AGENT_ORDER) | {"unknown"}, now),
            "errors": [],
            "fetchedAt": state.get("fetchedAt", 0.0),
        }, backoff, bool(cached))
        failure["ok"] = False
        failure["exitCode"] = result.get("exitCode")
        failure["error"] = result.get("error") or compact(
            result.get("stderr") or result.get("stdout") or "lazyagent returned invalid data", 400)
        return failure

    fresh = [{**report, "fetched_at": now, "stale": False} for report in limits["reports"]]
    fresh_agents = {report["agent"] for report in fresh}
    failed_agents = {error["agent"] for error in limits["errors"] if error["kind"] == "error"}
    rate_limited = sorted({error["agent"] for error in limits["errors"] if error["rate_limited"]})

    last_good = [report for report in state.get("lastGood", [])
                 if now - float(report.get("fetched_at", 0.0)) <= STALE_MAX_AGE_SECONDS]
    stale = stale_copies(last_good, failed_agents - fresh_agents, now)
    last_good = [report for report in last_good if report["agent"] not in fresh_agents] + fresh

    if rate_limited:
        backoff = next_backoff(backoff, now, "rate limited: " + ", ".join(rate_limited))
    else:
        backoff = {"until": 0.0, "level": 0, "reason": ""}

    new_state = {
        "agent": agent,
        "fetchedAt": now,
        "path": binary,
        "versionText": version,
        "generatedAt": limits["generatedAt"],
        "reports": sort_reports(fresh + stale)[:MAX_REPORTS],
        "errors": limits["errors"],
        "backoff": backoff,
        "lastGood": sort_reports(last_good)[:MAX_REPORTS],
    }
    save_state(new_state)
    payload = payload_from(new_state, backoff, False)
    payload["exitCode"] = result.get("exitCode")
    return payload


# ---------------------------------------------------------------- command


def parse_snapshot_args(args: list[str]) -> tuple[dict[str, Any] | None, str]:
    options: dict[str, Any] = {"agent": "all", "force": False, "max_age": 0.0}
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--agent" and index + 1 < len(args):
            options["agent"] = args[index + 1]
            index += 2
        elif token == "--force":
            options["force"] = True
            index += 1
        elif token == "--max-age" and index + 1 < len(args):
            value = args[index + 1]
            if not re.fullmatch(r"\d{1,7}", value):
                return None, "Invalid --max-age value"
            options["max_age"] = float(value)
            index += 2
        else:
            return None, "Unexpected snapshot arguments"
    return options, ""


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in {"-h", "--help", "help"}:
        return emit({
            "ok": True,
            "usage": "lazyagent_bridge.py probe|snapshot [--agent NAME] [--force] [--max-age SECONDS]",
        })

    command = argv[1]
    args = argv[2:]
    if command == "probe" and not args:
        return emit(probe())
    if command == "snapshot":
        options, error = parse_snapshot_args(args)
        if options is None:
            return emit({"ok": False, "error": error})
        return emit(snapshot(options["agent"], options["force"], options["max_age"]))
    return emit({"ok": False, "error": "Unknown bridge command"})


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except Exception as error:
        raise SystemExit(emit({"ok": False, "error": compact(str(error))}))
