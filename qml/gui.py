#!/usr/bin/env python3
"""
GUI launcher for Predator Control.
Provides a QObject bridge so QML can call the hardware backend.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtCore import QObject, Signal, Slot, Property, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from predator import (
    APP_ROOT,
    KeyboardController,
    KeyboardState,
    KB_EFFECTS,
    KB_EFFECTS_BY_NAME,
)


class KeyboardBridge(QObject):
    """QML-facing bridge to KeyboardController."""

    modeChanged = Signal()
    speedChanged = Signal()
    brightnessChanged = Signal()
    directionChanged = Signal()
    colorChanged = Signal()
    zoneColorsChanged = Signal()
    zoneBrightnessChanged = Signal()
    statusMessage = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state: KeyboardState = KeyboardController.get_state()
        self._zone_colors = list(self._state.per_zone.as_list())
        self._zone_brightness = self._state.per_zone.brightness
        if not self._state.available:
            self.statusMessage.emit(
                "Cannot read keyboard state. Are you in the 'linuwu_sense' group? "
                "Log out and back in, then try again.", False)

    # ── Properties ─────────────────────────────────────────────────

    def _get_mode(self):
        return self._state.mode

    def _get_speed(self):
        return self._state.speed

    def _get_brightness(self):
        return self._state.brightness

    def _get_direction(self):
        return self._state.direction

    def _get_hex_color(self):
        return self._state.hex_color

    def _get_zone_colors(self):
        return self._zone_colors

    def _get_zone_brightness(self):
        return self._zone_brightness

    mode = Property(int, _get_mode, notify=modeChanged)
    speed = Property(int, _get_speed, notify=speedChanged)
    brightness = Property(int, _get_brightness, notify=brightnessChanged)
    direction = Property(int, _get_direction, notify=directionChanged)
    hexColor = Property(str, _get_hex_color, notify=colorChanged)
    zoneColors = Property(list, _get_zone_colors, notify=zoneColorsChanged)
    zoneBrightness = Property(int, _get_zone_brightness, notify=zoneBrightnessChanged)

    # ── Slots ──────────────────────────────────────────────────────

    @Slot()
    def refresh(self):
        self._state = KeyboardController.get_state()
        self._zone_colors = list(self._state.per_zone.as_list())
        self._zone_brightness = self._state.per_zone.brightness
        self.modeChanged.emit()
        self.speedChanged.emit()
        self.brightnessChanged.emit()
        self.directionChanged.emit()
        self.colorChanged.emit()
        self.zoneColorsChanged.emit()
        self.zoneBrightnessChanged.emit()
        if not self._state.available:
            self.statusMessage.emit(
                "Cannot read keyboard state. Are you in the 'linuwu_sense' group? "
                "Log out and back in, then try again.", False)

    @Slot(int)
    def setMode(self, mode):
        self._state.mode = max(0, min(mode, 7))
        self.modeChanged.emit()

    @Slot(int)
    def setSpeed(self, speed):
        self._state.speed = max(0, min(speed, 9))
        self.speedChanged.emit()

    @Slot(int)
    def setBrightness(self, brightness):
        self._state.brightness = max(0, min(brightness, 100))
        self.brightnessChanged.emit()

    @Slot(int)
    def setDirection(self, direction):
        self._state.direction = max(0, min(direction, 2))
        self.directionChanged.emit()

    @Slot(str)
    def setHexColor(self, color):
        c = color.strip().lstrip("#")
        if len(c) == 6:
            try:
                self._state.red = int(c[0:2], 16)
                self._state.green = int(c[2:4], 16)
                self._state.blue = int(c[4:6], 16)
                self.colorChanged.emit()
            except ValueError:
                pass

    @Slot(int, str)
    def setZoneColor(self, zone, color):
        c = color.strip().lstrip("#")
        if 0 <= zone < 4 and len(c) == 6:
            try:
                int(c, 16)
                colors = list(self._zone_colors)
                colors[zone] = c
                self._zone_colors = colors
                self.zoneColorsChanged.emit()
            except ValueError:
                pass

    @Slot(int)
    def setZoneBrightness(self, brightness):
        self._zone_brightness = max(0, min(brightness, 100))
        self.zoneBrightnessChanged.emit()

    @Slot()
    def applyGlobalEffect(self):
        effect = KB_EFFECTS.get(self._state.mode, "Static")
        ok, _ = KeyboardController.set_global_effect(
            effect,
            self._state.speed,
            self._state.brightness,
            self._state.direction,
            self._state.hex_color,
        )
        if not ok:
            c = self._state.hex_color
            ok = self._elevate([
                str(APP_ROOT / "predator.py"), "keyboard", "--apply-mode",
                str(self._state.mode), str(self._state.speed),
                str(self._state.brightness), str(self._state.direction),
                str(int(c[0:2], 16)), str(int(c[2:4], 16)), str(int(c[4:6], 16)),
            ])
        if ok:
            self.refresh()
            self.statusMessage.emit("Global effect applied.", True)
        else:
            self.statusMessage.emit(
                "Failed to apply global effect. Are you in the linuwu_sense group?", False)

    @Slot()
    def applyZoneColors(self):
        ok, _ = KeyboardController.set_zone_colors(
            self._zone_colors[0],
            self._zone_colors[1],
            self._zone_colors[2],
            self._zone_colors[3],
            self._zone_brightness,
        )
        if not ok:
            ok = self._elevate([
                str(APP_ROOT / "predator.py"), "keyboard", "--apply-zones",
                self._zone_colors[0], self._zone_colors[1],
                self._zone_colors[2], self._zone_colors[3],
                str(self._zone_brightness),
            ])
        if ok:
            self.refresh()
            self.statusMessage.emit("Zone colors applied.", True)
        else:
            self.statusMessage.emit(
                "Failed to apply zone colors. Are you in the linuwu_sense group?", False)

    def _elevate(self, argv) -> bool:
        """Retry a write as root via password-less sudo."""
        try:
            r = subprocess.run(["sudo", "-n", *argv],
                               capture_output=True, text=True,
                               env={**os.environ, "PREDATOR_ELEVATED": "1"})
        except FileNotFoundError:
            return False
        return r.returncode == 0

    @Slot(result=list)
    def effectNames(self):
        return list(KB_EFFECTS.values())


def main(selftest: bool = False):
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Predator Control")
    app.setApplicationDisplayName("Predator Control")
    app.setOrganizationName("PredatorControl")

    engine = QQmlApplicationEngine()
    bridge = KeyboardBridge()
    engine.rootContext().setContextProperty("backend", bridge)

    qml_dir = Path(__file__).parent
    engine.addImportPath(str(qml_dir))
    engine.load(QUrl.fromLocalFile(str(qml_dir / "Main.qml")))

    if not engine.rootObjects():
        print("Error: Failed to load QML interface.", file=sys.stderr)
        sys.exit(1)

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)

    if selftest:
        # Initialization check: verify QML loaded and backend works,
        # then exit without opening a window to the user.
        print("Predator Control GUI initialized OK.")
        sys.exit(0)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()