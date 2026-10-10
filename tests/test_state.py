#!/usr/bin/env python3
"""Unit tests for StateStore persistence, power args, and privilege selection."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

import predator


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.orig_dir = predator.STATE_DIR
        self.orig_ac = predator.STATE_AC_FILE
        self.orig_bat = predator.STATE_BATTERY_FILE
        predator.STATE_DIR = self.tmp
        predator.STATE_AC_FILE = self.tmp / "state-ac.json"
        predator.STATE_BATTERY_FILE = self.tmp / "state-battery.json"

    def tearDown(self):
        predator.STATE_DIR = self.orig_dir
        predator.STATE_AC_FILE = self.orig_ac
        predator.STATE_BATTERY_FILE = self.orig_bat
        for p in self.tmp.glob("*"):
            p.unlink()
        self.tmp.rmdir()

    def test_save_load_roundtrip(self):
        snap = {
            "version": predator.STATE_VERSION,
            "power": "ac",
            "fans": {"cpu": 50, "gpu": 60, "available": True},
            "profile": "balanced",
            "battery_limiter": True,
            "battery_calibration": False,
            "keyboard_four_zone": {"mode": 0, "speed": 0, "brightness": 100,
                                   "direction": 0, "r": 0, "g": 0, "b": 0,
                                   "available": True},
            "keyboard_zones": {"z1": "ff0000", "z2": "00ff00", "z3": "0000ff",
                               "z4": "ffffff", "brightness": 80},
        }
        self.assertTrue(predator.StateStore.save("ac", dict(snap)))
        state, note = predator.StateStore.load("ac")
        self.assertIsNotNone(state)
        self.assertIsNone(note)
        self.assertEqual(state["fans"], snap["fans"])

    def test_load_missing_returns_missing(self):
        state, note = predator.StateStore.load("ac")
        self.assertIsNone(state)
        self.assertEqual(note, "missing")

    def test_load_corrupt_returns_corrupt(self):
        predator.STATE_AC_FILE.write_text("{not json")
        state, note = predator.StateStore.load("ac")
        self.assertIsNone(state)
        self.assertEqual(note, "corrupt")

    def test_load_bad_version(self):
        predator.STATE_AC_FILE.write_text('{"version": 999}')
        state, note = predator.StateStore.load("ac")
        self.assertIsNone(state)
        self.assertEqual(note, "version")

    def test_load_falls_back_with_note(self):
        predator.STATE_BATTERY_FILE.write_text(
            '{"version": %d, "profile": "quiet"}' % predator.STATE_VERSION)
        state, note = predator.StateStore.load("ac")
        self.assertIsNotNone(state)
        self.assertEqual(note, "fallback:battery")

    def test_coerce_bool_strings(self):
        self.assertTrue(predator.StateStore._coerce_bool("on"))
        self.assertTrue(predator.StateStore._coerce_bool("True"))
        self.assertFalse(predator.StateStore._coerce_bool("false"))
        self.assertFalse(predator.StateStore._coerce_bool("0"))
        self.assertFalse(predator.StateStore._coerce_bool("off"))

    def test_clean_hex_rejects_bad(self):
        self.assertEqual(predator.StateStore._clean_hex("ff0000"), "ff0000")
        self.assertEqual(predator.StateStore._clean_hex("xyz"), "000000")
        self.assertEqual(predator.StateStore._clean_hex("12345"), "000000")
        self.assertEqual(predator.StateStore._clean_hex(None), "000000")


class PowerArgTests(unittest.TestCase):
    def test_unknown_rejected(self):
        with self.assertRaises(SystemExit):
            predator._parse_power_arg(["typo"])

    def test_known_values(self):
        self.assertEqual(predator._parse_power_arg([]), "auto")
        self.assertEqual(predator._parse_power_arg(["ac"]), "ac")
        self.assertEqual(predator._parse_power_arg(["battery"]), "battery")
        self.assertEqual(predator._parse_power_arg(["both"]), "both")
        self.assertEqual(predator._parse_power_arg(["help"]), "help")


class PrivilegeTests(unittest.TestCase):
    def test_restore_help_does_not_escalate(self):
        self.assertFalse(predator._needs_privilege("restore", ["help"]))

    def test_keyboard_apply_escalates(self):
        self.assertTrue(predator._needs_privilege(
            "keyboard", ["--apply-mode", "0", "0", "100", "0", "0", "0", "0"]))

    def test_case_insensitive_status(self):
        self.assertFalse(predator._needs_privilege("fans", ["STATUS"]))


if __name__ == "__main__":
    unittest.main()
