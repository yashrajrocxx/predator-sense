#!/usr/bin/env python3
"""Validation unit tests (pure logic, no hardware, no sysfs)."""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from predator import (
    validate_fan_percent,
    validate_color_hex,
    validate_brightness,
    validate_speed,
    validate_direction,
    validate_battery_limit,
    KB_EFFECTS,
    KB_EFFECTS_BY_NAME,
    PROFILE_MAP,
)


class TestValidation(unittest.TestCase):
    def test_fan_percent(self):
        self.assertEqual(validate_fan_percent("0", "CPU"), 0)
        self.assertEqual(validate_fan_percent("100", "CPU"), 100)
        for bad in ("-1", "101", "abc", "50.5", "", "  ", "5 0"):
            with self.assertRaises(SystemExit):
                validate_fan_percent(bad, "CPU")

    def test_color_hex(self):
        self.assertEqual(validate_color_hex("00aec7"), "00aec7")
        self.assertEqual(validate_color_hex("#00AEC7"), "00aec7")
        self.assertEqual(validate_color_hex("aBc123"), "abc123")
        for bad in ("00ae", "1234567", "gggggg", "00aec", "#", "#12345", "12 345"):
            with self.assertRaises(SystemExit):
                validate_color_hex(bad)

    def test_brightness(self):
        self.assertEqual(validate_brightness("0"), 0)
        self.assertEqual(validate_brightness("100"), 100)
        for bad in ("-1", "101", "abc", "50.5"):
            with self.assertRaises(SystemExit):
                validate_brightness(bad)

    def test_speed(self):
        self.assertEqual(validate_speed("0"), 0)
        self.assertEqual(validate_speed("9"), 9)
        for bad in ("-1", "10", "abc"):
            with self.assertRaises(SystemExit):
                validate_speed(bad)

    def test_direction(self):
        self.assertEqual(validate_direction("0"), 0)
        self.assertEqual(validate_direction("2"), 2)
        for bad in ("-1", "3", "abc"):
            with self.assertRaises(SystemExit):
                validate_direction(bad)

    def test_battery_limit(self):
        self.assertEqual(validate_battery_limit("80"), 1)
        self.assertEqual(validate_battery_limit("100"), 0)
        self.assertEqual(validate_battery_limit("0"), 0)
        self.assertEqual(validate_battery_limit("1"), 1)
        for bad in ("101", "-1", "abc", "50.5"):
            with self.assertRaises(SystemExit):
                validate_battery_limit(bad)


class TestEffectTable(unittest.TestCase):
    def test_names(self):
        expected = {
            0: "Static", 1: "Breathing", 2: "Neon", 3: "Wave",
            4: "Shifting", 5: "Zoom", 6: "Meteor", 7: "Twinkling",
        }
        self.assertEqual(KB_EFFECTS, expected)
        for name, mode in KB_EFFECTS_BY_NAME.items():
            self.assertEqual(KB_EFFECTS[mode].lower(), name)

    def test_names_by_name(self):
        self.assertEqual(KB_EFFECTS_BY_NAME["static"], 0)
        self.assertEqual(KB_EFFECTS_BY_NAME["twinkling"], 7)


class TestProfileMap(unittest.TestCase):
    def test_map(self):
        self.assertEqual(PROFILE_MAP["quiet"], "quiet")
        self.assertEqual(PROFILE_MAP["bal"], "balanced")
        self.assertEqual(PROFILE_MAP["balanced"], "balanced")
        self.assertEqual(PROFILE_MAP["perf"], "performance")
        self.assertEqual(PROFILE_MAP["performance"], "performance")
        self.assertEqual(PROFILE_MAP["balanced-performance"], "balanced-performance")
        self.assertEqual(PROFILE_MAP["low-power"], "low-power")
        self.assertEqual(PROFILE_MAP["turbo"], "performance")


if __name__ == "__main__":
    unittest.main()