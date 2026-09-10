#!/usr/bin/env python3
"""Unit tests for the integrated uninstall command (no real sudo)."""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

import predator


class MockCompleted:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


class UninstallPathTests(unittest.TestCase):
    def test_app_paths_are_the_canonical_set(self):
        self.assertEqual(predator.APP_INSTALLABLE_PATHS, [
            "/opt/predator-control",
            "/usr/local/bin/predator",
            "/usr/share/applications/predator.desktop",
            "/etc/tmpfiles.d/predator-control.conf",
            "/etc/sudoers.d/predator-control",
        ])

    @mock.patch.object(os, "geteuid", return_value=0)
    def test_removes_paths_as_root(self, _geteuid):
        with mock.patch.object(predator.shutil, "rmtree") as rmtree, \
             mock.patch.object(Path, "unlink") as unlink, \
             mock.patch.object(Path, "is_dir", return_value=False), \
             mock.patch.object(Path, "is_symlink", return_value=True):
            ok, failures = predator._uninstall_paths([Path("/opt/predator-control")])
            self.assertTrue(ok)
            self.assertEqual(failures, [])
            unlink.assert_called_once_with(missing_ok=True)
            rmtree.assert_not_called()

    @mock.patch.object(os, "geteuid", return_value=1000)
    def test_uses_sudo_when_not_root(self, _geteuid):
        with mock.patch.object(subprocess, "run",
                               return_value=MockCompleted()) as run:
            ok, failures = predator._uninstall_paths([Path("/tmp/x")])
            self.assertTrue(ok)
            args = run.call_args[0][0]
            self.assertEqual(args[0], "sudo")
            self.assertIn("/tmp/x", args)

    @mock.patch.object(os, "geteuid", return_value=1000)
    def test_reports_failure(self, _geteuid):
        with mock.patch.object(subprocess, "run",
                               return_value=MockCompleted(rc=1, err="denied")):
            ok, failures = predator._uninstall_paths([Path("/tmp/x")])
            self.assertFalse(ok)
            self.assertTrue(any("denied" in f for f in failures))


_collect_count = 0
_verify_count = 0


def _collect_exists(_self):
    global _collect_count
    _collect_count += 1
    return _collect_count <= 4


def _verify_exists(_self):
    global _verify_count
    _verify_count += 1
    return _verify_count <= 8


class UninstallCliTests(unittest.TestCase):
    @mock.patch.object(predator, "_uninstall_paths", return_value=(True, []))
    @mock.patch.object(Path, "exists", autospec=True, side_effect=_collect_exists)
    @mock.patch.object(Path, "is_symlink", return_value=True)
    def test_yes_removes_paths(self, _symlink, _exists, _uninstall):
        with mock.patch("builtins.input") as fake_input:
            predator.cmd_uninstall(["--yes"])
            fake_input.assert_not_called()
            _uninstall.assert_called_once()

    @mock.patch.object(predator, "_uninstall_paths")
    @mock.patch.object(Path, "exists", autospec=True, side_effect=_verify_exists)
    @mock.patch.object(Path, "is_symlink", return_value=True)
    def test_answer_no_aborts(self, _symlink, _exists, uninstall):
        with mock.patch("builtins.input", return_value="n"), \
             self.assertRaises(SystemExit) as ctx:
            predator.cmd_uninstall([])
        self.assertEqual(ctx.exception.code, 0)
        uninstall.assert_not_called()

    @mock.patch.object(predator, "_uninstall_paths", return_value=(True, []))
    @mock.patch.object(Path, "exists", autospec=True, side_effect=_collect_exists)
    @mock.patch.object(Path, "is_symlink", return_value=True)
    def test_answer_yes_runs(self, _symlink, _exists, _uninstall):
        with mock.patch("builtins.input", return_value="yes"):
            predator.cmd_uninstall([])
        _uninstall.assert_called_once()

    @mock.patch.object(Path, "exists", return_value=False)
    @mock.patch.object(Path, "is_symlink", return_value=False)
    def test_nothing_installed(self, _symlink, _exists):
        with mock.patch.object(predator, "_uninstall_paths") as uninstall, \
             self.assertRaises(SystemExit) as ctx:
            predator.cmd_uninstall(["--yes"])
        self.assertEqual(ctx.exception.code, 0)
        uninstall.assert_not_called()


if __name__ == "__main__":
    unittest.main()