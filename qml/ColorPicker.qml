import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property string initialColor: "#000000"
    signal colorChanged(string color)

    property alias red: rSlider.value
    property alias green: gSlider.value
    property alias blue: bSlider.value
    property string hexColor:
        "#" + toHex(rSlider.value) + toHex(gSlider.value) + toHex(bSlider.value)

    function toHex(v) {
        var h = Math.round(v).toString(16).toUpperCase()
        return h.length === 1 ? "0" + h : h
    }

    function parseHex(h) {
        var clean = ("#" + h).replace("#", "")
        if (clean.length !== 6) return false
        var r = parseInt(clean.substring(0, 2), 16)
        var g = parseInt(clean.substring(2, 4), 16)
        var b = parseInt(clean.substring(4, 6), 16)
        if (isNaN(r) || isNaN(g) || isNaN(b)) return false
        rSlider.value = r
        gSlider.value = g
        bSlider.value = b
        return true
    }

    onInitialColorChanged: parseHex(initialColor)
    Component.onCompleted: parseHex(initialColor)

    function emitColor() {
        colorChanged(hexColor.substring(1))
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 34
            radius: 4
            border.color: palette.mid
            border.width: 1
            gradient: Gradient {
                GradientStop { position: 0.0; color: hexColor }
                GradientStop { position: 1.0; color: hexColor }
            }
            Text {
                anchors.centerIn: parent
                text: hexColor.toUpperCase()
                color: "#ffffff"
                font.bold: true
                style: Text.Outline
                styleColor: "#000000"
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text { text: "R"; color: "#ef5350"; font.bold: true; Layout.preferredWidth: 16 }
            Slider {
                id: rSlider
                Layout.fillWidth: true
                from: 0; to: 255; stepSize: 1; snapMode: Slider.SnapOnRelease
                onMoved: emitColor()
            }
            Text { text: Math.round(rSlider.value); Layout.preferredWidth: 32; horizontalAlignment: Text.AlignRight }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text { text: "G"; color: "#66bb6a"; font.bold: true; Layout.preferredWidth: 16 }
            Slider {
                id: gSlider
                Layout.fillWidth: true
                from: 0; to: 255; stepSize: 1; snapMode: Slider.SnapOnRelease
                onMoved: emitColor()
            }
            Text { text: Math.round(gSlider.value); Layout.preferredWidth: 32; horizontalAlignment: Text.AlignRight }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text { text: "B"; color: "#42a5f5"; font.bold: true; Layout.preferredWidth: 16 }
            Slider {
                id: bSlider
                Layout.fillWidth: true
                from: 0; to: 255; stepSize: 1; snapMode: Slider.SnapOnRelease
                onMoved: emitColor()
            }
            Text { text: Math.round(bSlider.value); Layout.preferredWidth: 32; horizontalAlignment: Text.AlignRight }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text { text: "Hex:"; font.bold: true }
            TextField {
                id: hexField
                Layout.preferredWidth: 100
                text: hexColor.substring(1)
                maximumLength: 6
                selectByMouse: true
                inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText
                onAccepted: {
                    var v = text.replace(/[^0-9a-fA-F]/g, "")
                    if (parseHex(v)) emitColor()
                }
            }
            Item { Layout.fillWidth: true }
        }
    }
}