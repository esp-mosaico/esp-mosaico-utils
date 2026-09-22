"""Validate the destructive runner's command routing without touching a device."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

RECOVERY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RECOVERY.parent / "mosaico-tools/tools"))
from mosaico_cli.cli import build_parser

spec = importlib.util.spec_from_file_location("crash_acceptance", RECOVERY / "tests/iris_crash_acceptance/run.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class CrashRunnerCommandsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.runner = acceptance.Runner("device", 240, self.workspace, Path("projects/custom_app"))
        self.calls = []

    def command(self, argv, **kwargs):
        args = build_parser().parse_args(argv[2:])
        self.assertEqual(args.workspace, str(self.workspace))
        self.assertEqual(kwargs["cwd"], self.workspace)
        self.calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "ok": True, "devices": [{"device_id": "device", "online": True}],
            "report": {"reports": [{}]}, "archive": {}}), stderr="")

    def test_fixture_install_and_restore_transfer_and_update_full_layout(self):
        with patch.object(acceptance.subprocess, "run", side_effect=self.command):
            self.runner.install_project("fixture", acceptance.FIXTURE)
            self.runner.install_project("restore", self.runner.application)
        self.assertEqual([args.public_command for args in self.calls], [
            "iris takeover start", "iris system-update", "iris takeover start", "iris system-update"])
        self.assertEqual([args.project for args in self.calls], [
            str(acceptance.FIXTURE), str(acceptance.FIXTURE),
            str(self.workspace / "projects/custom_app"), str(self.workspace / "projects/custom_app")])

    def test_read_rpc_and_recovery_commands_keep_the_selected_project(self):
        self.runner.active_project = acceptance.FIXTURE
        with patch.object(acceptance.subprocess, "run", side_effect=self.command):
            self.runner.list_device()
            self.runner.rpc("test-rpc", 1)
            self.runner.inspect_crash("test-report")
            self.runner.command("test-recover", "recover", "--source", "current")
        self.assertEqual([args.public_command for args in self.calls], [
            "iris list", "iris rpc", "iris crash", "recover"])
        self.assertTrue(all(args.project == str(acceptance.FIXTURE) for args in self.calls))


if __name__ == "__main__":
    unittest.main()
