import QtQuick
import Quickshell.Io
import "Model.js" as Model

// State for the Lazyagent widget. One bounded process, scripts/lazyagent_bridge.py,
// runs `lazyagent limits --json` and hands back a sanitised document. Nothing
// here ever builds a shell command: the argument array is fixed and the only
// variable part, the agent filter, is validated on both sides.
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
  // Wall-clock instant the last successful snapshot arrived. Countdowns and
  // "updated N ago" are derived from it rather than from lazyagent's own
  // timestamps, which carry nanoseconds the JS Date parser does not accept.
  property double fetchedAtMs: 0
  property double nowMs: Date.now()

  readonly property bool refreshing: snapshotProcess.running
  readonly property bool busy: refreshing
  readonly property int refreshIntervalSec: settingInt("refreshIntervalSec", 300, 60, 3600)
  readonly property string agentFilter: settingAgent("agent", "all")
  readonly property var failures: Model.errorsOfKind(errors, "error")
  readonly property real headlineUsed: Model.headlineUsed(reports)
  readonly property int worstSeverity: Model.worstSeverity(reports)
  readonly property bool overutilizing: Model.anyOverutilizing(reports)
  readonly property string statusText: Model.statusText(
    loaded, installed, refreshing, reports, errors)

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

  function refresh() {
    if (snapshotProcess.running) return
    var command = [bridgePath, "snapshot"]
    if (agentFilter !== "all") command.push("--agent", agentFilter)
    snapshotProcess.command = command
    snapshotProcess.running = true
  }

  // Opening the panel refreshes only when the data is stale, so a user who
  // opens and closes it repeatedly does not hammer undocumented endpoints.
  function refreshIfStale(maxAgeSec) {
    if (!loaded) { refresh(); return }
    var age = (Date.now() - fetchedAtMs) / 1000
    if (age >= maxAgeSec) refresh()
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
    if (payload.ok === false) {
      snapshotError = _cleanError(payload.error, "Could not read limits")
      loaded = true
      return
    }
    generatedAt = String(payload.generatedAt || "")
    reports = Array.isArray(payload.reports) ? payload.reports : []
    errors = Array.isArray(payload.errors) ? payload.errors : []
    snapshotError = ""
    fetchedAtMs = Date.now()
    nowMs = fetchedAtMs
    loaded = true
  }

  onAgentFilterChanged: if (loaded) refresh()

  property string _output: ""
  property string _errorOutput: ""

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
    onTriggered: root.refresh()
  }

  // Ticks the countdowns while the panel is open. Idle otherwise.
  Timer {
    interval: 1000
    running: root.panelOpen
    repeat: true
    triggeredOnStart: true
    onTriggered: root.nowMs = Date.now()
  }

  Component.onDestruction: {
    if (snapshotProcess.running) snapshotProcess.signal(15)
  }
}
