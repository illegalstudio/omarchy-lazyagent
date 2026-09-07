import QtQuick
import qs.Commons

// Horizontal gauge drawn as a shape, so it takes the theme colour directly
// and stays crisp at bar size. The fill follows the most used window, so
// the icon itself tells you how close the tightest limit is; a dot marks
// the alarm states (a nearly exhausted window, or overutilizing pace).
Item {
  id: root

  property real iconSize: Style.bar.iconCanvas
  property color color: Color.foreground
  // 0..1 fraction of the tightest window; negative means unknown.
  property real level: -1
  property bool warning: false
  property bool alert: false
  property bool dimmed: false

  readonly property real strokeWidth: Math.max(1, iconSize * 0.1)
  readonly property color ink: alert ? Color.urgent : color

  width: iconSize
  height: iconSize
  implicitWidth: width
  implicitHeight: height
  opacity: dimmed ? 0.55 : 1.0

  Rectangle {
    id: frame
    anchors.centerIn: parent
    width: root.iconSize * 0.92
    height: root.iconSize * 0.5
    radius: height * 0.3
    color: "transparent"
    border.width: root.strokeWidth
    border.color: root.ink
  }

  Rectangle {
    anchors.left: frame.left
    anchors.verticalCenter: frame.verticalCenter
    anchors.leftMargin: root.strokeWidth * 2
    height: frame.height - root.strokeWidth * 4
    width: Math.max(0, (frame.width - root.strokeWidth * 4)
      * Math.max(0, Math.min(1, root.level)))
    radius: height * 0.3
    color: root.ink
    visible: root.level >= 0

    Behavior on width {
      NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
    }
  }

  // Unknown state: a short dash instead of a fill.
  Rectangle {
    visible: root.level < 0
    anchors.centerIn: frame
    width: frame.width * 0.32
    height: root.strokeWidth
    radius: height / 2
    color: root.ink
  }

  Rectangle {
    visible: root.warning || root.alert
    width: Math.max(3, root.iconSize * 0.2)
    height: width
    radius: width / 2
    anchors.right: parent.right
    anchors.top: parent.top
    color: root.alert ? Color.urgent : root.color
  }
}
