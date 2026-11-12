import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Bar button plus popup panel.
//
// The panel is a read-only dashboard of what `lazyagent limits --json`
// reports: one section per metered pool, one row per rate-limit window,
// each with the used percentage, the linear pace expectation, lazyagent's
// pace verdict (underutilizing / on track / overutilizing) and the reset
// countdown. Everything is computed by lazyagent; this file only lays it out.
Panel {
  id: root

  moduleName: "illegalstudio.omarchy-lazyagent"
  ipcTarget: "illegalstudio.omarchy-lazyagent"
  manageIpc: false

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color background: bar ? bar.background : Color.background
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color track: Style.selectedFillFor(foreground, Color.accent)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property bool alarming: backend.worstSeverity >= 3
  readonly property bool attention: backend.overutilizing || backend.failures.length > 0
    || backend.snapshotError !== ""
  readonly property string versionTag: {
    var match = String(backend.lazyagentVersion).match(/v?(\d+\.\d+\.\d+)/)
    return match ? "v" + match[1] : ""
  }
  readonly property string tooltipText: Model.tooltipText(
    backend.loaded, backend.installed, backend.reports, backend.errors)

  // Pools whose More section is open, keyed by poolKey(). Kept here rather
  // than in ReportSection so a refresh that rebuilds the sections keeps it.
  property var expandedPools: ({})

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function poolKey(report) {
    return String((report && report.agent) || "") + "/" + String((report && report.provider) || "")
  }

  function setExpanded(key, value) {
    var next = {}
    for (var name in expandedPools) next[name] = expandedPools[name]
    next[key] = value
    expandedPools = next
  }

  // M opens every More section, or closes them all when any is open.
  function toggleAllMore() {
    var reports = Model.toList(backend.reports)
    var anyOpen = false
    for (var i = 0; i < reports.length; i++) {
      if (expandedPools[poolKey(reports[i])] === true) anyOpen = true
    }
    var next = {}
    for (var j = 0; j < reports.length; j++) {
      if (Model.hasExtras(reports[j])) next[poolKey(reports[j])] = !anyOpen
    }
    expandedPools = next
  }

  function clamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, value))
  }

  function scrollBy(rows) {
    panelFlick.contentY = clamp(panelFlick.contentY + rows * Style.space(56), 0,
      Math.max(0, panelFlick.contentHeight - panelFlick.height))
  }

  onOpenedChanged: {
    backend.panelOpen = opened
    if (opened) {
      panelFlick.contentY = 0
      backend.refresh("open")
      Qt.callLater(function() { keyCatcher.forceActiveFocus() })
    }
  }

  Service {
    id: backend
    settings: root.settings
    panelOpen: root.opened
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): string { backend.refresh("manual"); return "ok" }
    function more(): string { root.toggleAllMore(); return "ok" }
    function status(): string { return backend.statusText }
    function debug(): string {
      return JSON.stringify({
        opened: root.opened,
        installed: backend.installed,
        path: backend.lazyagentPath,
        version: backend.lazyagentVersion,
        agent: backend.agentFilter,
        reports: backend.reports.length,
        errors: backend.errors.length,
        headlineUsed: backend.headlineUsed,
        worstSeverity: backend.worstSeverity,
        snapshotError: backend.snapshotError,
        fromCache: backend.fromCache,
        fetchedAt: backend.fetchedAtMs,
        backoffUntil: backend.backoffUntilMs,
        backoffLevel: backend.backoffLevel,
        backoffReason: backend.backoffReason,
        anyStale: backend.anyStale
      })
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    tooltipText: root.tooltipText
    active: root.opened
    iconComponent: Component {
      LimitsIcon {
        anchors.centerIn: parent
        iconSize: Style.bar.iconCanvas
        color: root.barForeground
        level: backend.headlineUsed >= 0 ? backend.headlineUsed / 100 : -1
        alert: root.alarming
        warning: root.attention
        dimmed: backend.loaded && !backend.installed
      }
    }
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton) backend.refresh()
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(760))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent

      onMoveRequested: function(dx, dy) { if (dy !== 0) root.scrollBy(dy) }
      onActivateRequested: backend.refresh()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) {
        var key = String(text).toLowerCase()
        if (key === "r") backend.refresh()
        else if (key === "m") root.toggleAllMore()
      }

      Flickable {
        id: panelFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        WheelHandler {
          acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
          onWheel: function(event) {
            var maximumY = panelFlick.contentHeight - panelFlick.height
            if (maximumY <= 0) return
            panelFlick.contentY = root.clamp(
              panelFlick.contentY - event.angleDelta.y, 0, maximumY)
          }
        }

        Column {
          id: column
          width: panelFlick.width
          spacing: Style.space(12)

          PanelHero {
            width: parent.width
            title: "Lazyagent"
            meta: backend.statusText
            detail: root.versionTag
            foreground: root.foreground
            fontFamily: root.fontFamily
            iconComponent: Component {
              LimitsIcon {
                iconSize: Style.font.display
                color: root.foreground
                level: backend.headlineUsed >= 0 ? backend.headlineUsed / 100 : -1
                alert: root.alarming
                warning: root.attention
                dimmed: backend.loaded && !backend.installed
              }
            }
            trailingControl: Component {
              PanelActionButton {
                iconText: "󰑐"
                tooltipText: backend.inBackoff
                  ? "Refresh now, ignoring the backoff (R)" : "Refresh limits (R)"
                foreground: root.foreground
                enabled: !backend.busy
                onClicked: backend.refresh()
              }
            }
          }

          Notice {
            visible: backend.snapshotError !== ""
            width: parent.width
            tone: root.urgent
            text: backend.snapshotError
          }

          Column {
            visible: backend.loaded && !backend.installed
            width: parent.width
            spacing: Style.space(8)

            Notice {
              width: parent.width
              tone: root.urgent
              text: "lazyagent is required. On Omarchy, install the Arch package from the lazyagent release page (an AUR package is coming), then click Check again."
            }

            RowLayout {
              spacing: Style.space(8)

              Button {
                text: "Installation instructions"
                bordered: true
                foreground: root.foreground
                fontFamily: root.fontFamily
                focusable: false
                onClicked: Qt.openUrlExternally("https://github.com/illegalstudio/omarchy-lazyagent#install")
              }

              Button {
                text: "Check again"
                iconText: "󰑐"
                bordered: true
                foreground: root.foreground
                fontFamily: root.fontFamily
                focusable: false
                enabled: !backend.busy
                onClicked: backend.refresh()
              }
            }
          }

          Text {
            visible: !backend.loaded
            width: parent.width
            topPadding: Style.space(16)
            bottomPadding: Style.space(16)
            textFormat: Text.PlainText
            text: "Reading rate limits through lazyagent…"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
          }

          Text {
            visible: backend.loaded && backend.installed && backend.reports.length === 0
              && backend.snapshotError === "" && backend.failures.length === 0
            width: parent.width
            topPadding: Style.space(16)
            bottomPadding: Style.space(16)
            textFormat: Text.PlainText
            text: "No agents are reporting limits.\nLog in to Claude Code, Codex, Grok, Kimi, or Cursor and refresh."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
          }

          // Index-based on purpose: a JS object handed over as modelData is
          // converted to a QVariantMap on the way, and its nested arrays stop
          // looking like arrays. Reading it back from the source keeps the
          // original JS value.
          Repeater {
            model: backend.reports.length

            ReportSection {
              required property int index
              width: parent.width
              report: index < backend.reports.length ? backend.reports[index] : ({})
            }
          }

          Column {
            visible: backend.failures.length > 0
            width: parent.width
            spacing: Style.space(8)

            PanelSeparator { foreground: root.foreground }

            PanelSectionHeader {
              text: "ISSUES"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Repeater {
              model: backend.failures

              Notice {
                required property var modelData
                width: parent.width
                tone: root.urgent
                text: Model.issueText(modelData, backend.reports, backend.nowMs,
                  backend.backoffRemainingSec)
              }
            }
          }

          Notice {
            visible: text !== "" && backend.installed
            width: parent.width
            text: Model.silentAgentsText(backend.errors)
          }

          RowLayout {
            visible: backend.loaded && backend.installed
            width: parent.width
            spacing: Style.space(8)

            Text {
              Layout.fillWidth: true
              textFormat: Text.PlainText
              text: backend.refreshing ? "Refreshing…"
                : Model.agoText(backend.fetchedAtMs, backend.nowMs)
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }

            Text {
              textFormat: Text.PlainText
              text: backend.agentFilter === "all" ? "M more  ·  R refresh"
                : Model.agentName(backend.agentFilter) + " only  ·  M more  ·  R refresh"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          Item {
            width: 1
            height: Style.space(2)
          }
        }
      }
    }
  }

  component Notice: Text {
    property color tone: root.dim

    textFormat: Text.PlainText
    color: tone
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }

  // One metered pool: provider header and one LimitRow per window.
  component ReportSection: Column {
    id: section

    property var report: ({})
    readonly property var windows: Model.windowsOf(report)
    readonly property string staleLabel: Model.staleText(report, backend.nowMs)
    readonly property double fetchedAtMs: Model.reportFetchedAtMs(report, backend.fetchedAtMs)
    readonly property var resets: Model.resetsOf(report)
    readonly property var credits: Model.creditsOf(report)
    readonly property bool hasExtras: Model.hasExtras(report)
    readonly property string key: root.poolKey(report)
    readonly property bool expanded: hasExtras && root.expandedPools[key] === true

    spacing: Style.space(8)

    PanelSeparator { foreground: root.foreground }

    RowLayout {
      width: parent.width
      spacing: Style.space(8)

      PanelSectionHeader {
        Layout.fillWidth: true
        text: String(section.report.provider || section.report.agent || "").toUpperCase()
        foreground: root.foreground
        fontFamily: root.fontFamily
        elide: Text.ElideRight
      }

      // Kept from an earlier snapshot because the agent failed this time.
      BorderSurface {
        visible: section.staleLabel !== ""
        implicitWidth: staleText.implicitWidth + Style.space(10)
        implicitHeight: staleText.implicitHeight + Style.space(4)
        color: "transparent"
        borderSpec: Border.controlSpec("normal", root.urgent, root.urgent)
        radius: Style.cornerRadius

        Text {
          id: staleText
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: section.staleLabel
          color: root.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }

      Text {
        visible: section.windows.length === 0
        textFormat: Text.PlainText
        text: "No windows"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Column {
      width: parent.width
      spacing: Style.space(10)

      Repeater {
        model: section.windows.length

        LimitRow {
          required property int index
          width: parent.width
          window: index < section.windows.length ? section.windows[index] : ({})
          fetchedAtMs: section.fetchedAtMs
          stale: section.staleLabel !== ""
        }
      }
    }

    // Resets, extra credits and provenance stay behind More so the
    // windows remain scannable at a glance.
    RowLayout {
      visible: section.hasExtras
      width: parent.width
      spacing: Style.space(8)

      Button {
        text: section.expanded ? "Less" : "More"
        iconText: section.expanded ? "󰅃" : "󰅀"
        foreground: root.foreground
        fontFamily: root.fontFamily
        fontSize: Style.font.caption
        iconSize: Style.font.caption
        horizontalPadding: Style.space(6)
        verticalPadding: Style.space(2)
        bordered: true
        focusable: false
        onClicked: root.setExpanded(section.key, !section.expanded)
      }

      Text {
        Layout.fillWidth: true
        visible: !section.expanded
        textFormat: Text.PlainText
        text: Model.extrasSummary(section.report)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }

    Column {
      visible: section.expanded
      width: parent.width
      spacing: Style.space(10)
      opacity: section.staleLabel !== "" ? 0.72 : 1.0

      Column {
        visible: section.resets.length > 0
        width: parent.width
        spacing: Style.space(8)

        ExtrasHeader { text: "Limit resets" }

        Repeater {
          model: section.resets.length

          ResetRow {
            required property int index
            width: parent.width
            reset: index < section.resets.length ? section.resets[index] : ({})
            fetchedAtMs: section.fetchedAtMs
          }
        }
      }

      Column {
        visible: section.credits.length > 0
        width: parent.width
        spacing: Style.space(8)

        ExtrasHeader { text: "Extra credits" }

        Repeater {
          model: section.credits.length

          CreditRow {
            required property int index
            width: parent.width
            credit: index < section.credits.length ? section.credits[index] : ({})
          }
        }
      }

      Notice {
        visible: text !== ""
        width: parent.width
        font.pixelSize: Style.font.caption
        text: [String(section.report.source || ""), String(section.report.note || "")]
          .filter(function(line) { return line !== "" }).join("\n")
      }
    }
  }

  component ExtrasHeader: Text {
    textFormat: Text.PlainText
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
  }

  // A banked limit reset: label and how many are left, then whether it can
  // be redeemed now and when it lapses or comes back. lazyagent only
  // reports resets; redeeming one stays in the provider's own client.
  component ResetRow: Column {
    id: resetRow

    property var reset: ({})
    property double fetchedAtMs: backend.fetchedAtMs
    readonly property bool usable: Model.resetUsable(reset)

    spacing: Style.space(2)

    RowLayout {
      width: parent.width
      spacing: Style.space(8)

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: String(resetRow.reset.label || "Limit reset")
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
      }

      Text {
        Layout.alignment: Qt.AlignTop
        textFormat: Text.PlainText
        text: Model.resetCountText(resetRow.reset)
        color: resetRow.usable ? root.foreground : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
      }
    }

    Text {
      visible: text !== ""
      width: parent.width
      textFormat: Text.PlainText
      text: Model.resetDetail(resetRow.reset, resetRow.fetchedAtMs, backend.nowMs)
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }
  }

  // A balance or spend pool beyond the included usage, with a thin meter
  // when the provider reports spend against a limit.
  component CreditRow: Column {
    id: creditRow

    property var credit: ({})
    readonly property real fraction: Model.creditFraction(credit)

    spacing: Style.space(4)
    opacity: creditRow.credit.enabled === true ? 1.0 : 0.72

    RowLayout {
      width: parent.width
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        text: String(creditRow.credit.label || "Credits")
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: Model.creditText(creditRow.credit)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        horizontalAlignment: Text.AlignRight
        wrapMode: Text.WordWrap
      }
    }

    Item {
      visible: creditRow.fraction >= 0
      width: parent.width
      implicitHeight: Math.max(Style.space(4), Math.round(Style.spacing.controlHeight * 0.12))

      Rectangle {
        id: creditTrack
        anchors.fill: parent
        radius: height / 2
        color: root.track
      }

      Rectangle {
        anchors.left: creditTrack.left
        anchors.verticalCenter: creditTrack.verticalCenter
        height: creditTrack.height
        radius: creditTrack.radius
        width: creditTrack.width * Math.max(0, creditRow.fraction)
        color: creditRow.fraction >= 0.9 ? root.urgent : root.foreground
      }
    }
  }

  // A rate-limit window: label and used %, meter with the expected-pace
  // marker, then the pace verdict and the reset countdown.
  component LimitRow: Column {
    id: limitRow

    property var window: ({})
    property double fetchedAtMs: backend.fetchedAtMs
    property bool stale: false

    readonly property bool alarming: Model.windowAlarming(window)
    readonly property string tone: Model.paceTone(window)
    readonly property color paceColor: tone === "over" ? root.urgent
      : (tone === "track" ? root.foreground : root.dim)
    readonly property real usedFraction: root.clamp(
      Model.asNumber(window.used_percent, 0) / 100, 0, 1)
    readonly property real expectedFraction: root.clamp(
      Model.asNumber(window.expected_percent, 0) / 100, 0, 1)

    spacing: Style.space(5)
    opacity: stale ? 0.72 : 1.0

    Item {
      width: parent.width
      implicitHeight: Math.max(windowLabel.implicitHeight, usedValue.implicitHeight)

      Text {
        id: windowLabel
        textFormat: Text.PlainText
        text: Model.windowTitle(limitRow.window)
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        elide: Text.ElideRight
        anchors.left: parent.left
        anchors.right: usedValue.left
        anchors.rightMargin: Style.spacing.sm
        anchors.verticalCenter: parent.verticalCenter
      }

      Text {
        id: usedValue
        textFormat: Text.PlainText
        text: Model.percentText(limitRow.window.used_percent) + " used"
        color: limitRow.alarming ? root.urgent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        font.bold: true
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
      }
    }

    Item {
      id: meter
      width: parent.width
      implicitHeight: Math.max(Style.space(6), Math.round(Style.spacing.controlHeight * 0.2))

      Rectangle {
        id: meterTrack
        anchors.fill: parent
        radius: height / 2
        color: root.track
      }

      Rectangle {
        anchors.left: meterTrack.left
        anchors.verticalCenter: meterTrack.verticalCenter
        height: meterTrack.height
        radius: meterTrack.radius
        width: meterTrack.width * limitRow.usedFraction
        color: limitRow.alarming ? root.urgent : root.foreground

        Behavior on width {
          NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
        }
      }

      // Where a perfectly linear consumer would be right now.
      Rectangle {
        visible: limitRow.window.pace_known === true
        width: Math.max(2, Style.space(2))
        height: meterTrack.height + Style.space(6)
        radius: 1
        color: root.foreground
        anchors.verticalCenter: meterTrack.verticalCenter
        x: root.clamp(meterTrack.width * limitRow.expectedFraction - width / 2,
          0, meterTrack.width - width)

        Rectangle {
          anchors.fill: parent
          anchors.margins: -Style.space(1)
          radius: 2
          color: Color.popups.background
          z: -1
        }
      }
    }

    // Breathing room between the meter and the verdict row.
    Item {
      width: 1
      height: Style.space(3)
    }

    RowLayout {
      width: parent.width
      spacing: Style.space(8)

      BorderSurface {
        implicitWidth: paceText.implicitWidth + Style.space(10)
        implicitHeight: paceText.implicitHeight + Style.space(4)
        color: "transparent"
        borderSpec: Border.controlSpec("normal", limitRow.paceColor, limitRow.paceColor)
        radius: Style.cornerRadius

        Text {
          id: paceText
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: Model.paceText(limitRow.window)
          color: limitRow.paceColor
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }

      Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        text: Model.paceDetail(limitRow.window, limitRow.fetchedAtMs, backend.nowMs)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }

      Text {
        textFormat: Text.PlainText
        text: Model.resetText(limitRow.window, limitRow.fetchedAtMs, backend.nowMs)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    // Provider context, such as a scoped window's share of the plan-wide
    // limit ("11% of the weekly limit used, capped at 50%").
    Text {
      visible: text !== ""
      width: parent.width
      textFormat: Text.PlainText
      text: String(limitRow.window.detail || "")
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }
  }
}
