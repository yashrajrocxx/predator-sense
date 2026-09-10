#!/usr/bin/env python3
"""Unit tests for validation and backend logic (no real hardware)."""
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


class FakeFile:
    def __init__(self, content="0,0"):
        self.content = content

    def read_text(self):
        return self.content

    def write_text(self, value):
        self.content = value


import predator
from predator import (
    FanState,
    ProfileState,
    BatteryState,
    ZoneColor,
    KeyboardState,
    Telemetry,
    SystemStatus,
)


class TestValidation(unittest.TestCase):
    def test_fan_percent_valid(self):
        self.assertEqual(predator.validate_fan_percent("0", "x"), 0)
        self.assertEqual(predator.validate_fan_percent("50", "x"), 50)
        self.assertEqual(predator.validate_fan_percent("100", "x"), 100)

    def test_fan_percent_rejects_negative(self):
        with self.assertRaises(SystemExit):
            predator.validate_fan_percent("-1", "x")

    def test_fan_percent_rejects_over_100(self):
        with self.assertRaises(SystemExit):
            predator.validate_fan_percent("101", "x")

    def test_fan_percent_rejects_non_int(self):
        with self.assertRaises(SystemExit):
            predator.validate_fan_percent("abc", "x")
        with self.assertRaises(SystemExit):
            predator.validate_fan_percent("50.5", "x")

    def test_color_hex_valid(self):
        self.assertEqual(predator.validate_color_hex("00aec7"), "00aec7")
        self.assertEqual(predator.validate_color_hex("#00AEC7"), "00aec7")
        self.assertEqual(predator.validate_color_hex("FFFFFF"), "ffffff")

    def test_color_hex_rejects_bad(self):
        for bad in ("00ae", "1234567", "gggggg", "xyz", "#12345"):
            with self.assertRaises(SystemExit):
                predator.validate_color_hex(bad)

    def test_brightness_valid(self):
        self.assertEqual(predator.validate_brightness("0"), 0)
        self.assertEqual(predator.validate_brightness("100"), 100)

    def test_brightness_rejects_bad(self):
        for bad in ("-1", "101", "abc"):
            with self.assertRaises(SystemExit):
                predator.validate_brightness(bad)

    def test_speed_valid(self):
        self.assertEqual(predator.validate_speed("0"), 0)
        self.assertEqual(predator.validate_speed("9"), 9)

    def test_speed_rejects_bad(self):
        for bad in ("-1", "10", "abc"):
            with self.assertRaises(SystemExit):
                predator.validate_speed(bad)

    def test_direction_valid(self):
        self.assertEqual(predator.validate_direction("0"), 0)
        self.assertEqual(predator.validate_direction("2"), 2)

    def test_direction_rejects_bad(self):
        for bad in ("-1", "3", "abc"):
            with self.assertRaises(SystemExit):
                predator.validate_direction(bad)

    def test_battery_limit_mapping(self):
        self.assertEqual(predator.validate_battery_limit("80"), 1)
        self.assertEqual(predator.validate_battery_limit("0"), 0)
        self.assertEqual(predator.validate_battery_limit("100"), 0)

    def test_battery_limit_rejects_bad(self):
        for bad in ("101", "-1", "abc"):
            with self.assertRaises(SystemExit):
                predator.validate_battery_limit(bad)


class TestDataclasses(unittest.TestCase):
    def test_fan_state_auto(self):
        self.assertTrue(FanState(0, 0).is_auto)
        self.assertFalse(FanState(50, 50).is_auto)

    def test_fan_state_max(self):
        self.assertTrue(FanState(100, 100).is_max)
        self.assertFalse(FanState(50, 50).is_max)

    def test_fan_state_str(self):
        self.assertEqual(str(FanState(0, 0)), "Auto")
        self.assertEqual(str(FanState(100, 100)), "Max")

    def test_keyboard_effect_name(self):
        self.assertEqual(KeyboardState(mode=0).effect_name, "Static")
        self.assertEqual(KeyboardState(mode=4).effect_name, "Shifting")

    def test_hex_color(self):
        k = KeyboardState(red=0, green=174, blue=199)
        self.assertEqual(k.hex_color, "00aec7")

    def test_profile_short_name(self):
        self.assertEqual(ProfileState(current="performance").short_name, "turbo")
        self.assertEqual(ProfileState(current="balanced").short_name, "balanced")


class TestProfileMapping(unittest.TestCase):
    def test_map(self):
        self.assertEqual(predator.PROFILE_MAP["quiet"], "quiet")
        self.assertEqual(predator.PROFILE_MAP["bal"], "balanced")
        self.assertEqual(predator.PROFILE_MAP["perf"], "performance")
        self.assertEqual(predator.PROFILE_MAP["turbo"], "performance")
        self.assertNotIn("doesnotexist", predator.PROFILE_MAP)


class TestKbEffects(unittest.TestCase):
    def test_effects(self):
        self.assertEqual(len(predator.KB_EFFECTS), 8)
        self.assertEqual(predator.KB_EFFECTS[0], "Static")
        self.assertEqual(predator.KB_EFFECTS[7], "Twinkling")
        self.assertEqual(predator.KB_EFFECTS_BY_NAME["shifting"], 4)


class TestSysfsHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp = Path("/tmp/predator_test_sysfs")
        self.tmp.mkdir(exist_ok=True)
        self.tmp.joinpath("testfile").write_text("42\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_read_ok(self):
        self.assertEqual(predator.read_sysfs(self.tmp / "testfile"), "42")

    def test_read_missing(self):
        self.assertIsNone(predator.read_sysfs(self.tmp / "nope"))

    def test_read_permission_denied(self):
        f = self.tmp / "testfile"
        f.chmod(0o000)
        self.assertIsNone(predator.read_sysfs(f))
        f.chmod(0o644)

    def test_write_ok(self):
        f = self.tmp / "testfile"
        self.assertTrue(predator.write_sysfs(f, "99"))
        self.assertEqual(f.read_text(), "99")

    def test_write_missing(self):
        self.assertFalse(predator.write_sysfs(self.tmp / "nope", "1"))

    def test_exists(self):
        self.assertTrue(predator.exists_sysfs(self.tmp / "testfile"))
        self.assertFalse(predator.exists_sysfs(self.tmp / "nope"))


class TestFanController(unittest.TestCase):
    def test_fan_parse(self):
        orig = predator.read_sysfs
        predator.read_sysfs = lambda p: "50,70"
        try:
            s = predator.FanController.get_state()
            self.assertEqual((s.cpu, s.gpu), (50, 70))
        finally:
            predator.read_sysfs = orig


class TestBatteryController(unittest.TestCase):
    def test_battery_parse(self):
        orig = predator.read_sysfs
        def fake(p):
            return {
                "battery_limiter": "1",
                "battery_calibration": "0",
                "capacity": "80",
                "status": "Charging",
            }.get(p.name, None)
        predator.read_sysfs = fake
        try:
            s = predator.BatteryController.get_state()
            self.assertTrue(s.limiter_enabled)
            self.assertFalse(s.calibration_enabled)
            self.assertEqual(s.capacity, 80)
        finally:
            predator.read_sysfs = orig


class TestKeyboardController(unittest.TestCase):
    def test_four_zone_parse(self):
        orig = predator.read_sysfs
        def fake(p):
            if p == predator.FOUR_ZONE_MODE:
                return "4,3,100,1,0,174,199"
            if p == predator.PER_ZONE_MODE:
                return "00aec7,00aec7,00aec7,00aec7,100"
            return None
        predator.read_sysfs = fake
        try:
            s = predator.KeyboardController.get_state()
            self.assertEqual(s.mode, 4)
            self.assertEqual(s.speed, 3)
            self.assertEqual(s.brightness, 100)
            self.assertEqual(s.direction, 1)
            self.assertEqual(s.hex_color, "00aec7")
            self.assertEqual(s.per_zone.zone1, "00aec7")
            self.assertEqual(s.per_zone.brightness, 100)
        finally:
            predator.read_sysfs = orig


if __name__ == "__main__":
    unittest.main()