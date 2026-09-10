import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

Window {
    id: root
    title: "Predator Keyboard Control"
    width: 540
    height: 660
    minimumWidth: 480
    minimumHeight: 560
    visible: true
    color: palette.window

    property int currentZone: 0
    property bool initialized: false

    Component.onCompleted: initialize()

    function initialize() {
        if (!backend || initialized) return
        initialized = true
        backend.refresh()
        effectCombo.currentIndex = backend.mode
        speedSlider.value = backend.speed
        directionCombo.currentIndex = backend.direction
        globalBrightnessSlider.value = backend.brightness
        zoneBrightnessSlider.value = backend.zoneBrightness
    }

    Connections {
        target: backend
        function onStatusMessage(msg, ok) {
            statusBar.text = msg
            statusBar.color = ok ? "#2e7d32" : "#c62828"
            statusTimer.restart()
        }
        function onModeChanged() {
            effectCombo.currentIndex = backend.mode
        }
        function onBrightnessChanged() {
            globalBrightnessSlider.value = backend.brightness
        }
        function onSpeedChanged() {
            speedSlider.value = backend.speed
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        Text {
            text: "Predator Keyboard RGB"
            font.pixelSize: 18
            font.bold: true
            Layout.alignment: Qt.AlignHCenter
        }

        KeyboardVisualization {
            id: keyboardVis
            Layout.fillWidth: true
            Layout.preferredHeight: 80
            zoneColors: backend ? backend.zoneColors : ["000000","000000","000000","000000"]
            currentZone: root.currentZone
            onZoneClicked: function(zone) {
                root.currentZone = zone
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text { text: "Zone:"; font.bold: true }
            ButtonGroup {
                id: zoneGroup
            }
            Repeater {
                model: ["Z1", "Z2", "Z3", "Z4"]
                RadioButton {
                    id: zoneBtn
                    text: modelData
                    checked: index === root.currentZone
                    ButtonGroup.group: zoneGroup
                    onCheckedChanged: if (checked) root.currentZone = index
                }
            }
            Item { Layout.fillWidth: true }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: palette.mid }

        TabBar {
            id: tabBar
            Layout.fillWidth: true
            currentIndex: 0
            TabButton { text: "Per Zone" }
            TabButton { text: "Global Effect" }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabBar.currentIndex

            ScrollView {
                clip: true
                ColumnLayout {
                    width: parent.width
                    spacing: 12
                    anchors.margins: 4

                    Text {
                        text: "Zone " + (root.currentZone + 1) + " Color"
                        font.bold: true
                    }

                    ColorPicker {
                        id: zonePicker
                        Layout.fillWidth: true
                        Layout.preferredHeight: 200
                        initialColor: root.backend
                            ? "#" + root.backend.zoneColors[root.currentZone]
                            : "#000000"
                        onColorChanged: function(c) {
                            if (backend && initialized) {
                                backend.setZoneColor(root.currentZone, c)
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Brightness:" }
                        Slider {
                            id: zoneBrightnessSlider
                            Layout.fillWidth: true
                            from: 0; to: 100; stepSize: 1; snapMode: Slider.SnapOnRelease
                            value: backend ? backend.zoneBrightness : 100
                            onMoved: if (backend) backend.setZoneBrightness(Math.round(value))
                        }
                        Text { text: Math.round(zoneBrightnessSlider.value) + "%"; Layout.preferredWidth: 40 }
                    }

                    Button {
                        text: "Apply Zone Colors"
                        Layout.fillWidth: true
                        highlighted: true
                        onClicked: if (backend) backend.applyZoneColors()
                    }
                }
            }

            ScrollView {
                clip: true
                ColumnLayout {
                    width: parent.width
                    spacing: 12
                    anchors.margins: 4

                    Text { text: "Global Effect"; font.bold: true }

                    ComboBox {
                        id: effectCombo
                        Layout.fillWidth: true
                        model: backend ? backend.effectNames() : ["Static","Breathing","Neon","Wave","Shifting","Zoom","Meteor","Twinkling"]
                        currentIndex: backend ? backend.mode : 0
                        onCurrentIndexChanged: if (backend && initialized) backend.setMode(currentIndex)
                    }

                    ColorPicker {
                        id: globalPicker
                        Layout.fillWidth: true
                        Layout.preferredHeight: 200
                        initialColor: backend ? "#" + backend.hexColor : "#000000"
                        visible: effectCombo.currentIndex !== 2 && effectCombo.currentIndex !== 3
                        onColorChanged: function(c) {
                            if (backend && initialized) backend.setHexColor(c)
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: effectCombo.currentIndex !== 0 && effectCombo.currentIndex !== 1 && effectCombo.currentIndex !== 2 && effectCombo.currentIndex !== 3
                        Text { text: "Speed:" }
                        Slider {
                            id: speedSlider
                            Layout.fillWidth: true
                            from: 0; to: 9; stepSize: 1; snapMode: Slider.SnapOnRelease
                            value: backend ? backend.speed : 0
                            onMoved: if (backend) backend.setSpeed(Math.round(value))
                        }
                        Text { text: Math.round(speedSlider.value); Layout.preferredWidth: 20 }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: effectCombo.currentIndex === 3 || effectCombo.currentIndex === 4
                        Text { text: "Direction:" }
                        ComboBox {
                            id: directionCombo
                            model: ["Left", "Right", "Up"]
                            currentIndex: backend ? backend.direction : 0
                            onCurrentIndexChanged: if (backend && initialized) backend.setDirection(currentIndex)
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "Brightness:" }
                        Slider {
                            id: globalBrightnessSlider
                            Layout.fillWidth: true
                            from: 0; to: 100; stepSize: 1; snapMode: Slider.SnapOnRelease
                            value: backend ? backend.brightness : 100
                            onMoved: if (backend && initialized) backend.setBrightness(Math.round(value))
                        }
                        Text { text: Math.round(globalBrightnessSlider.value) + "%"; Layout.preferredWidth: 40 }
                    }

                    Button {
                        text: "Apply Global Effect"
                        Layout.fillWidth: true
                        highlighted: true
                        onClicked: if (backend) backend.applyGlobalEffect()
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Item { Layout.fillWidth: true }
            Button { text: "Refresh"; onClicked: if (backend) backend.refresh() }
        }

        Text {
            id: statusBar
            Layout.fillWidth: true
            text: ""
            visible: text !== ""
            font.pixelSize: 12
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
        }

        Timer {
            id: statusTimer
            interval: 4000
            onTriggered: statusBar.text = ""
        }
    }
}