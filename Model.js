.pragma library

// Pure helpers shared by Panel.qml and Service.qml. Plain ES5 with no Qt
// imports so tests/model.test.js can load it under node.

function asNumber(value, fallback) {
  var number = Number(value)
  return isFinite(number) ? number : (fallback === undefined ? 0 : fallback)
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value))
}

// Copies an array-like into a plain JS array. Objects that cross a Repeater
// boundary arrive as QVariantMap/QVariantList, and Array.isArray is false
// for the latter even though it indexes and reports a length.
function toList(value) {
  if (!value || typeof value === "string" || typeof value.length !== "number") return []
  var result = []
  for (var i = 0; i < value.length; i++) result.push(value[i])
  return result
}

function percentText(value) {
  var number = asNumber(value, 0)
  var rounded = Math.round(number * 10) / 10
  var text = rounded.toFixed(1).replace(/\.0$/, "")
  return text + "%"
}

function ratioText(value) {
  var number = asNumber(value, 0)
  if (number >= 10) return Math.round(number) + "×"
  return (Math.round(number * 100) / 100).toFixed(2).replace(/\.?0+$/, "") + "×"
}

// Seconds → "1h 19m", "6d 17h", "12m", "45s". Mirrors lazyagent's own
// reset_relative so the countdown keeps the same shape as it ticks.
function formatDuration(seconds) {
  var total = Math.max(0, Math.floor(asNumber(seconds, 0)))
  if (total < 60) return total + "s"
  var days = Math.floor(total / 86400)
  var hours = Math.floor((total % 86400) / 3600)
  var minutes = Math.floor((total % 3600) / 60)
  if (days > 0) return days + "d " + hours + "h"
  if (hours > 0) return hours + "h " + minutes + "m"
  return minutes + "m"
}

// Remaining seconds for a window, based on the moment the snapshot was
// received rather than on parsing resets_at (which carries nanoseconds).
function remainingSeconds(window, fetchedAtMs, nowMs) {
  if (!window) return 0
  var base = asNumber(window.reset_in_seconds, 0)
  if (base <= 0) return 0
  var elapsed = (asNumber(nowMs, 0) - asNumber(fetchedAtMs, 0)) / 1000
  return Math.max(0, base - Math.max(0, elapsed))
}

function resetText(window, fetchedAtMs, nowMs) {
  var remaining = remainingSeconds(window, fetchedAtMs, nowMs)
  if (remaining <= 0) {
    return window && window.resets_at ? "Reset due" : ""
  }
  return "Resets in " + formatDuration(remaining)
}

function agoText(fetchedAtMs, nowMs) {
  if (!fetchedAtMs || fetchedAtMs <= 0) return ""
  var seconds = Math.max(0, (asNumber(nowMs, 0) - fetchedAtMs) / 1000)
  if (seconds < 10) return "Updated just now"
  return "Updated " + formatDuration(seconds) + " ago"
}

// Seconds left in a provider backoff, 0 when none is active.
function backoffRemaining(untilMs, nowMs) {
  var until = asNumber(untilMs, 0)
  if (until <= 0) return 0
  return Math.max(0, (until - asNumber(nowMs, 0)) / 1000)
}

// Milliseconds of the report's own fetch, or the fallback when the report
// carries none. Stale reports keep the instant they were actually read.
function reportFetchedAtMs(report, fallbackMs) {
  var seconds = report ? asNumber(report.fetched_at, 0) : 0
  return seconds > 0 ? seconds * 1000 : asNumber(fallbackMs, 0)
}

// "Stale · 12m ago" for a report kept from an earlier snapshot, else "".
function staleText(report, nowMs) {
  if (!report || report.stale !== true) return ""
  var fetched = reportFetchedAtMs(report, 0)
  if (fetched <= 0) return "Stale"
  var seconds = Math.max(0, (asNumber(nowMs, 0) - fetched) / 1000)
  return "Stale · " + formatDuration(seconds) + " ago"
}

function reportFor(reports, agent) {
  var list = toList(reports)
  for (var i = 0; i < list.length; i++) {
    if (String(list[i].agent || "") === String(agent || "")) return list[i]
  }
  return null
}

function anyStale(reports) {
  var list = toList(reports)
  for (var i = 0; i < list.length; i++) {
    if (list[i].stale === true) return true
  }
  return false
}

// One sentence for the Issues section. A rate-limited agent says when the
// next attempt is and, when an older report is on screen, how old it is.
function issueText(error, reports, nowMs, backoffRemainingSec) {
  if (!error) return ""
  var name = agentName(error.agent)
  if (error.rate_limited === true) {
    var text = name + ": rate limited by the provider."
    var remaining = asNumber(backoffRemainingSec, 0)
    text += remaining > 0
      ? " Retrying in " + formatDuration(remaining) + "."
      : " Retrying at the next refresh."
    var report = reportFor(reports, error.agent)
    if (report && report.stale === true) {
      var age = Math.max(0, (asNumber(nowMs, 0) - reportFetchedAtMs(report, 0)) / 1000)
      text += " Showing data from " + formatDuration(age) + " ago."
    }
    return text
  }
  return name + ": " + String(error.message || "limits unavailable")
}

// Pace as lazyagent defines it: used < 0.85 × elapsed is underutilizing,
// > 1.15 × is overutilizing. The label comes from lazyagent; this only maps
// it to a display string and a tone.
// lazyagent withholds the pace until 1% of the window has elapsed, since
// used/elapsed is meaningless right after a reset. Mirror its CLI wording.
function paceJustReset(window) {
  if (!window || window.pace_known === true) return false
  return asNumber(window.expected_percent, 0) < 1
    && asNumber(window.window_minutes, 0) > 0
}

// Seconds until 1% of the window has elapsed, counted from the snapshot's
// fetch instant so it keeps ticking while the panel is open.
function paceAvailableIn(window, fetchedAtMs, nowMs) {
  if (!paceJustReset(window)) return 0
  var windowSeconds = asNumber(window.window_minutes, 0) * 60
  var missing = (1 - asNumber(window.expected_percent, 0)) / 100 * windowSeconds
  var elapsed = Math.max(0, (asNumber(nowMs, 0) - asNumber(fetchedAtMs, 0)) / 1000)
  return Math.max(0, missing - elapsed)
}

function paceText(window) {
  if (paceJustReset(window)) return "Window just reset"
  if (!window || !window.pace_known || !window.pace_label) return "Pace unknown"
  var label = String(window.pace_label)
  return label.charAt(0).toUpperCase() + label.substring(1)
}

function paceDetail(window, fetchedAtMs, nowMs) {
  if (paceJustReset(window)) {
    var seconds = paceAvailableIn(window, fetchedAtMs, nowMs)
    return seconds > 0 ? "Pace in ~" + formatDuration(seconds)
      : "Pace at the next refresh"
  }
  if (!window || !window.pace_known) return ""
  return ratioText(window.pace_ratio) + " of expected " + percentText(window.expected_percent)
}

// "under" | "track" | "over" | "unknown"
function paceTone(window) {
  if (!window || !window.pace_known) return "unknown"
  var label = String(window.pace_label || "")
  if (label === "overutilizing") return "over"
  if (label === "underutilizing") return "under"
  if (label === "on track") return "track"
  return "unknown"
}

function severityRank(severity) {
  var value = String(severity || "default")
  if (value === "danger") return 3
  if (value === "warn") return 2
  if (value === "info") return 1
  return 0
}

function windowAlarming(window) {
  if (!window) return false
  return severityRank(window.used_severity) >= 2
    || asNumber(window.used_percent, 0) >= 90
}

function windowsOf(report) {
  return report ? toList(report.windows) : []
}

// Highest used percentage across every window: the number the bar icon
// fills up with, because it is the window that runs out first.
function headlineUsed(reports) {
  var best = -1
  var list = toList(reports)
  for (var i = 0; i < list.length; i++) {
    var windows = windowsOf(list[i])
    for (var j = 0; j < windows.length; j++) {
      best = Math.max(best, asNumber(windows[j].used_percent, 0))
    }
  }
  return best
}

function worstSeverity(reports) {
  var rank = 0
  var list = toList(reports)
  for (var i = 0; i < list.length; i++) {
    var windows = windowsOf(list[i])
    for (var j = 0; j < windows.length; j++) {
      rank = Math.max(rank, severityRank(windows[j].used_severity))
      if (asNumber(windows[j].used_percent, 0) >= 90) rank = Math.max(rank, 3)
    }
  }
  return rank
}

function anyOverutilizing(reports) {
  var list = toList(reports)
  for (var i = 0; i < list.length; i++) {
    var windows = windowsOf(list[i])
    for (var j = 0; j < windows.length; j++) {
      if (paceTone(windows[j]) === "over") return true
    }
  }
  return false
}

function errorsOfKind(errors, kind) {
  var result = []
  var list = toList(errors)
  for (var i = 0; i < list.length; i++) {
    if (String(list[i].kind || "") === kind) result.push(list[i])
  }
  return result
}

function agentName(agent) {
  var value = String(agent || "")
  if (value === "claude") return "Claude Code"
  if (value === "codex") return "Codex"
  if (value === "grok") return "Grok"
  if (value === "kimi") return "Kimi Code"
  if (value === "cursor") return "Cursor"
  return value === "" ? "Unknown agent" : value
}

function silentAgentsText(errors) {
  var names = []
  var list = toList(errors)
  for (var i = 0; i < list.length; i++) {
    var kind = String(list[i].kind || "")
    if (kind !== "not_installed" && kind !== "unavailable") continue
    var name = agentName(list[i].agent)
    if (names.indexOf(name) === -1) names.push(name)
  }
  if (names.length === 0) return ""
  return names.join(", ") + (names.length === 1 ? " is" : " are")
    + " not installed or not reporting."
}

function statusText(loaded, installed, refreshing, reports, errors, backoffRemainingSec) {
  if (!loaded) return refreshing ? "Reading limits" : "Waiting for lazyagent"
  if (!installed) return "lazyagent is not installed"
  var remaining = asNumber(backoffRemainingSec, 0)
  if (remaining > 0) return "Rate limited · retry in " + formatDuration(remaining)
  var count = toList(reports).length
  var failures = errorsOfKind(errors, "error").length
  if (count === 0 && failures > 0) return "Could not read any limits"
  if (count === 0) return "No agents reporting"
  var rank = worstSeverity(reports)
  if (rank >= 3) return "A window is nearly exhausted"
  if (anyOverutilizing(reports)) return "Overutilizing"
  return count + (count === 1 ? " pool" : " pools") + " reporting"
}

function tooltipText(loaded, installed, reports, errors) {
  if (!loaded) return "Lazyagent: checking limits"
  if (!installed) return "Lazyagent: lazyagent is not installed"
  var lines = []
  var list = toList(reports)
  for (var i = 0; i < list.length; i++) {
    var report = list[i]
    var summary = report.summary || {}
    var parts = []
    if (summary.five_hour) parts.push("5h " + percentText(summary.five_hour.used_percent))
    if (summary.week_global) parts.push("week " + percentText(summary.week_global.used_percent))
    if (parts.length === 0) {
      var windows = windowsOf(report)
      for (var j = 0; j < windows.length; j++) {
        parts.push(windows[j].label + " " + percentText(windows[j].used_percent))
      }
    }
    lines.push(String(report.short_name || report.provider || report.agent) + ": " + parts.join(" · ")
      + (report.stale === true ? "  (stale)" : ""))
  }
  if (lines.length === 0) {
    var failures = errorsOfKind(errors, "error")
    return failures.length > 0 ? "Lazyagent: " + String(failures[0].message || "limits unavailable")
      : "Lazyagent: no agents reporting"
  }
  return lines.join("\n")
}
