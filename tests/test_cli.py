#!/usr/bin/env python3
"""CLI tests - argument parsing, error handling, exit codes (mocked sysfs)."""
import io
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

import predator


@contextmanager
def capture():
    old_out, old_err = sys.stdout, sys.stderr
    out, err = io.StringIO(), io.StringIO()
    sys.stdout, sys.stderr = out, err
    try:
        yield out, err
    finally:
        sys.stdout, sys.stderr = old_out, old_err


class FakeSysfs:
    """Mirror of linuwu_sense sysfs tree with fake values."""

    def __init__(self):
        self.files = {
            "fan_speed": "50,50",
            "battery_limiter": "1",
            "battery_calibration": "0",
            "boot_animation_sound": "1",
            "lcd_override": "1",
            "usb_charging": "30",
            "backlight_timeout": "1",
            "version": "25.701",
            "four_zone_mode": "0,4,100,0,0,174,199",
            "per_zone_mode": "00aec7,00aec7,00aec7,00aec7,100",
            "platform_profile": "balanced",
            "platform_profile_choices": "low-power quiet balanced balanced-performance performance",
            "capacity": "80",
            "status": "Not charging",
        }
        self.write_log = []

    def read(self, path):
        assert str(path) == "/sys/firmware/acpi/platform_profile" or "predator" in str(path) \
            or str(path).endswith("/platform_profile_choices") or "BAT1" in str(path) \
            or "hwmon" in str(path), path
        for name, val in self.files.items():
            if path.name == name:
                return val
        return None

    def write(self, path, value):
        self.write_log.append((str(path), value.strip()))
        for name in self.files:
            if path.name == name:
                self.files[name] = value
                return True
        return True


class TestPanel:
    """Cheap stand-in: enables the driver for the fake tree."""

    def install(self):
        predator.DRIVER_BASE.is_dir  # no-op
        self.orig_read = predator.read_sysfs
        self.orig_write = predator.write_sysfs
        self.orig_exists = predator.exists_sysfs
        self.panel = FakeSysfs()
        predator.read_sysfs = self.panel.read
        predator.write_sysfs = self.panel.write
        predator.exists_sysfs = lambda p: True

    def uninstall(self):
        predator.read_sysfs = self.orig_read
        predator.write_sysfs = self.orig_write
        predator.exists_sysfs = self.orig_exists


fakepanel = TestPanel()


def setUpModule():
    fakepanel.install()


def tearDownModule():
    fakepanel.uninstall()


def run_cmd(cmd, args):
    """Invoke a CLI command function."""
    with capture() as (out, err):
        try:
            cmd(args)
            rc = 0
        except SystemExit as e:
            rc = e.code or 0
    return out.getvalue(), err.getvalue(), rc


class TestCliErrorHandling(unittest.TestCase):
    def test_fan_help(self):
        out, _, rc = run_cmd(predator.cmd_fans, ["help"])
        self.assertEqual(rc, 0)
        self.assertIn("Usage:", out)

    def test_fans_status(self):
        out, _, rc = run_cmd(predator.cmd_fans, ["status"])
        self.assertEqual(rc, 0)
        self.assertIn("CPU", out)
        self.assertIn("GPU", out)

    def test_fans_invalid_shows_error(self):
        _, err, rc = run_cmd(predator.cmd_fans, ["-1"])
        self.assertNotEqual(rc, 0)
        self.assertIn("Error", err)

    def test_fans_invalid_string(self):
        _, err, rc = run_cmd(predator.cmd_fans, ["abc"])
        self.assertNotEqual(rc, 0)
        self.assertIn("Error", err)

    def test_fans_float(self):
        _, err, rc = run_cmd(predator.cmd_fans, ["50.5"])
        self.assertNotEqual(rc, 0)

    def test_fans_two_args_valid(self):
        out, _, rc = run_cmd(predator.cmd_fans, ["50", "70"])
        self.assertEqual(rc, 0)
        self.assertIn("CPU=", out)
        self.assertIn("GPU=70", out)
        last = fakepanel.panel.write_log[-1]
        self.assertTrue(last[1].startswith("50"))

    def test_profile_status(self):
        out, _, rc = run_cmd(predator.cmd_profile, ["status"])
        self.assertEqual(rc, 0)
        self.assertIn("balanced", out)

    def test_profile_invalid(self):
        _, err, rc = run_cmd(predator.cmd_profile, ["doesnotexist"])
        self.assertNotEqual(rc, 0)

    def test_battery_status(self):
        out, _, rc = run_cmd(predator.cmd_battery, ["status"])
        self.assertEqual(rc, 0)
        self.assertIn("80", out)

    def test_turbo_status(self):
        out, _, rc = run_cmd(predator.cmd_turbo, ["status"])
        self.assertEqual(rc, 0)

    def test_driver_load_error(self):
        orig_check = predator.check_driver
        predator.check_driver = lambda: False
        try:
            _, err, rc = run_cmd(predator.cmd_fans, ["status"])
            self.assertNotEqual(rc, 0)
        finally:
            predator.check_driver = orig_check


class TestSysfsWriteVerification(unittest.TestCase):
    def test_fan_write_and_readback(self):
        out, _, rc = run_cmd(predator.cmd_fans, ["75", "80"])
        self.assertEqual(rc, 0)
        state = predator.FanController.get_state()
        self.assertEqual((state.cpu, state.gpu), (75, 80))

    def test_readback_mismatch_is_error(self):
        orig_get = predator.FanController.get_state
        predator.FanController.get_state = lambda: predator.FanState(0, 0)
        try:
            _, err, rc = run_cmd(predator.cmd_fans, ["90", "90"])
            self.assertNotEqual(rc, 0)
        finally:
            predator.FanController.get_state = orig_get


class TestPrivilegeSelection(unittest.TestCase):
    def test_read_commands_never_escalate(self):
        for cmd, args in [
            ("fans", ["status"]), ("fans", ["help"]),
            ("profile", ["status"]), ("profile", ["help"]),
            ("turbo", ["status"]), ("turbo", ["help"]),
            ("battery", ["status"]), ("battery", ["help"]),
            ("keyboard", []), ("keyboard", ["status"]),
            ("temps", []), ("status", []), ("self-test", []),
            ("uninstall", []),
        ]:
            self.assertFalse(predator._needs_privilege(cmd, args),
                             f"{cmd} {args} must not escalate")

    def test_write_commands_escalate(self):
        for cmd, args in [
            ("fans", ["auto"]), ("fans", ["max"]), ("fans", ["50", "70"]),
            ("profile", ["turbo"]), ("profile", ["bal"]),
            ("turbo", ["on"]), ("turbo", ["off"]),
            ("battery", ["limit", "80"]), ("battery", ["calibration", "on"]),
        ]:
            self.assertTrue(predator._needs_privilege(cmd, args),
                            f"{cmd} {args} must escalate")

    @mock.patch.object(predator, "_session_has_linuwu_sense_group", return_value=False)
    @mock.patch.object(predator.os, "geteuid", return_value=1000)
    def test_run_elevated_uses_sudo_when_stale_session(self, _euid, _has_group):
        probe = mock.Mock(returncode=0)
        run_mock = mock.Mock(returncode=0)
        with mock.patch.object(predator.subprocess, "run",
                               side_effect=[probe, run_mock]) as run:
            with self.assertRaises(SystemExit) as ctx:
                predator._run_elevated(["fans", "auto"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(run.call_count, 2)
        args = run.call_args_list[0][0][0]
        self.assertEqual(args[0], "sudo")
        self.assertEqual(args[1], "-n")
        self.assertEqual(args[2], "-l")
        args = run.call_args_list[1][0][0]
        self.assertEqual(args[0], "sudo")
        self.assertTrue(str(args[2]).endswith("predator.py"))
        self.assertIn("fans", args)

    @mock.patch.object(predator, "_session_has_linuwu_sense_group", return_value=False)
    @mock.patch.object(predator.os, "geteuid", return_value=1000)
    def test_run_elevated_skips_when_no_sudo_rule(self, _euid, _has_group):
        probe = mock.Mock(returncode=1)
        with mock.patch.object(predator.subprocess, "run",
                               side_effect=[probe]) as run:
            predator._run_elevated(["fans", "auto"])
        run.assert_called_once()

    @mock.patch.object(predator, "_session_has_linuwu_sense_group", return_value=True)
    @mock.patch.object(predator.os, "geteuid", return_value=1000)
    def test_run_elevated_skips_when_session_has_group(self, _euid, _has_group):
        with mock.patch.object(predator.subprocess, "run") as run:
            predator._run_elevated(["fans", "auto"])
        run.assert_not_called()

    def test_session_has_group_when_member(self):
        gid = 1001
        fake = mock.Mock(gr_gid=gid)
        with mock.patch("grp.getgrnam", return_value=fake), \
             mock.patch.object(predator.os, "getgroups", return_value=[gid]):
            self.assertTrue(predator._session_has_linuwu_sense_group())

    def test_session_lacks_group(self):
        fake = mock.Mock(gr_gid=1001)
        with mock.patch("grp.getgrnam", return_value=fake), \
             mock.patch.object(predator.os, "getgroups", return_value=[1000]):
            self.assertFalse(predator._session_has_linuwu_sense_group())


if __name__ == "__main__":
    unittest.main()