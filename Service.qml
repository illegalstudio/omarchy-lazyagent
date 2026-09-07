import QtQuick
import Quickshell.Io
import "Model.js" as Model

// State for the Lazyagent widget. One bounded process, scripts/lazyagent_bridge.py,
// runs `lazyagent limits --json` and hands back a sanitised document. Nothing
// here ever builds a shell command: the argument array is fixed and the only
// variable part, the agent filter, is validated on both sides.
//
// The bridge keeps a state file with the last snapshot, the last good report
// per agent, and any provider backoff. Every automatic refresh asks for
// "data no older than N seconds" and the bridge answers from that file when
// it can, so shell restarts and rate limits never turn into repeated calls
// against the providers' undocumented endpoints. Only a manual refresh forces
// a new lazyagent run.
Item {
  id: root

  property var settings: ({})
  property bool panelOpen: false

  readonly property string bridgePath: {
    var value = String(Qt.resolvedUrl("scripts/lazyagent_bridge.py"))
    return value.indexOf("file://") === 0
      ? decodeURIComponent(value.substring(7)) : value
  }

  property bool loaded: false
  property bool installed: false
  property string lazyagentPath: ""
  property string lazyagentVersion: ""
  property string generatedAt: ""
  property var reports: []
  property var errors: []
  property string snapshotError: ""
  // Instant the newest report in the snapshot was fetched, in ms. Comes from
  // the bridge so it survives a shell restart served from the cache.
  property double fetchedAtMs: 0
  property bool fromCache: false
  property double backoffUntilMs: 0
  property int backoffLevel: 0
  property string backoffReason: ""
  property double nowMs: Date.now()

  readonly property bool refreshing: snapshotProcess.running
  readonly property bool busy: refreshing
  readonly property int refreshIntervalSec: settingInt("refreshIntervalSec", 300, 60, 3600)
  readonly property string agentFilter: settingAgent("agent", "all")
  readonly property var failures: Model.errorsOfKind(errors, "error")
  readonly property real backoffRemainingSec: Model.backoffRemaining(backoffUntilMs, nowMs)
  readonly property bool inBackoff: backoffRemainingSec > 0
  readonly property bool anyStale: Model.anyStale(reports)
  readonly property real headlineUsed: Model.headlineUsed(reports)
  readonly property int worstSeverity: Model.worstSeverity(reports)
  readonly property bool overutilizing: Model.anyOverutilizing(reports)
  readonly property string statusText: Model.statusText(
    loaded, installed, refreshing, reports, errors, backoffRemainingSec)

  signal snapshotFinished(bool ok)

  function settingValue(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function settingInt(name, fallback, minimum, maximum) {
    var value = parseInt(String(settingValue(name, fallback)), 10)
    if (!isFinite(value)) value = fallback
    return Math.max(minimum, Math.min(maximum, value))
  }

  function settingAgent(name, fallback) {
    var value = String(settingValue(name, fallback)).toLowerCase().trim()
    var allowed = ["all", "claude", "codex", "grok", "kimi", "cursor"]
    return allowed.indexOf(value) === -1 ? fallback : value
  }

  function _append(which, data) {
    var text = String(data || "")
    var limit = 768 * 1024
    if (which === "out") _output = (_output + text).substring(0, limit)
    else _errorOutput = (_errorOutput + text).substring(0, limit)
  }

  function _payload(output, errorOutput) {
    var text = String(output || "").trim()
    if (text === "") text = String(errorOutput || "").trim()
    if (text === "") return null
    try {
      return JSON.parse(text)
    } catch (error) {
      return null
    }
  }

  function _cleanError(value, fallback) {
    var text = String(value || fallback || "Unknown error").replace(/\s+/g, " ").trim()
    return text.length > 240 ? text.substring(0, 237) + "..." : text
  }

  // mode: "manual" forces a lazyagent run; "startup", "timer" and "open"
  // accept cached data up to a mode-specific age and never break a backoff.
  function refresh(mode) {
    if (snapshotProcess.running) return
    var kind = String(mode || "manual")
    var command = [bridgePath, "snapshot"]
    if (agentFilter !== "all") command.push("--agent", agentFilter)
    if (kind === "manual") {
      command.push("--force")
    } else {
      var maxAge = kind === "startup" ? refreshIntervalSec
        : (kind === "open" ? 60 : 30)
      command.push("--max-age", String(Math.max(0, Math.round(maxAge))))
    }
    snapshotProcess.command = command
    snapshotProcess.running = true
  }

  function _applySnapshot(payload) {
    if (!payload) {
      snapshotError = "The lazyagent bridge returned invalid data"
      loaded = true
      return
    }
    installed = payload.installed === true
    lazyagentPath = String(payload.path || "")
    lazyagentVersion = String(payload.version || "")

    // A failed run still carries whatever the bridge could recover from its
    // cache, flagged stale, so a restart during an outage is not blank.
    var hasReports = Array.isArray(payload.reports)
    if (hasReports) {
      generatedAt = String(payload.generatedAt || "")
      reports = payload.reports
      errors = Array.isArray(payload.errors) ? payload.errors : []
      var fetched = Number(payload.fetchedAt)
      fetchedAtMs = isFinite(fetched) && fetched > 0 ? fetched * 1000 : 0
      fromCache = payload.fromCache === true
      var until = Number(payload.backoffUntil)
      backoffUntilMs = isFinite(until) && until > 0 ? until * 1000 : 0
      var level = parseInt(String(payload.backoffLevel), 10)
      backoffLevel = isFinite(level) ? Math.max(0, level) : 0
      backoffReason = String(payload.backoffReason || "")
    }
    snapshotError = payload.ok === false
      ? _cleanError(payload.error, "Could not read limits") : ""
    nowMs = Date.now()
    loaded = true
  }

  onAgentFilterChanged: if (loaded) refresh("manual")

  property string _output: ""
  property string _errorOutput: ""
  property bool _started: false

  Process {
    id: snapshotProcess
    running: false
    command: []
    stdout: SplitParser {
      splitMarker: ""
      onRead: function(data) { root._append("out", data) }
    }
    stderr: SplitParser {
      splitMarker: ""
      onRead: function(data) { root._append("err", data) }
    }
    onStarted: {
      root._output = ""
      root._errorOutput = ""
    }
    onExited: function(exitCode) {
      var payload = root._payload(root._output, root._errorOutput)
      root._applySnapshot(payload)
      if (!payload && exitCode !== 0)
        root.snapshotError = "Could not run the lazyagent bridge"
      root.snapshotFinished(payload !== null && payload.ok !== false)
    }
  }

  Timer {
    interval: root.refreshIntervalSec * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: {
      root.refresh(root._started ? "timer" : "startup")
      root._started = true
    }
  }

  // Drives countdowns, "updated N ago" and the backoff clock. Ticks every
  // second while the panel is open and slowly otherwise, so the bar icon
  // still notices when a backoff ends.
  Timer {
    interval: root.panelOpen ? 1000 : 30000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.nowMs = Date.now()
  }

  Component.onDestruction: {
    if (snapshotProcess.running) snapshotProcess.signal(15)
  }
}
