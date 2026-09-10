import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    property var zoneColors: ["000000", "000000", "000000", "000000"]
    property int currentZone: 0
    signal zoneClicked(int zone)

    color: palette.base
    border.color: palette.mid
    border.width: 1
    radius: 4

    RowLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 6

        Repeater {
            model: 4
            delegate: Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 4
                color: "#" + root.zoneColors[index]
                border.color: index === root.currentZone ? palette.highlight : palette.mid
                border.width: index === root.currentZone ? 3 : 1

                Text {
                    anchors.centerIn: parent
                    text: "Z" + (index + 1)
                    color: "white"
                    font.bold: true
                    font.pixelSize: 14
                    style: Text.Outline
                    styleColor: "black"
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: root.zoneClicked(index)
                    cursorShape: Qt.PointingHandCursor
                }
            }
        }
    }
}
