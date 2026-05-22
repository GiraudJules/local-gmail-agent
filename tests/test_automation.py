from __future__ import annotations

import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from local_gmail_agent.automation import (
    build_launchd_plist,
    build_runner_script,
    install_launch_agent,
    installed_launch_agent_path,
    is_launch_agent_loaded,
    parse_daily_time,
    uninstall_launch_agent,
)
from local_gmail_agent.automation_store import (
    AutomationJob,
    find_automation_job,
    job_paths,
    list_automation_jobs,
    remove_automation_job,
    save_automation_job,
)
from local_gmail_agent.cli import app


class AutomationHelpersTestCase(unittest.TestCase):
    def test_parse_daily_time(self) -> None:
        self.assertEqual(parse_daily_time("23:15"), (23, 15))

    def test_build_runner_script_contains_cd_and_command(self) -> None:
        script = build_runner_script(
            Path("/tmp/project"),
            ["uv", "run", "local-gmail-agent", "automation", "run", "--id", "abc"],
        )

        self.assertIn("cd /tmp/project", script)
        self.assertIn("automation run --id abc", script)

    def test_build_launchd_plist_supports_interval(self) -> None:
        plist_text = build_launchd_plist(
            label="com.example.test",
            script_path=Path("/tmp/run.sh"),
            stdout_path=Path("/tmp/out.log"),
            stderr_path=Path("/tmp/err.log"),
            start_interval_seconds=3600,
        )
        payload = plistlib.loads(plist_text.encode("utf-8"))

        self.assertEqual(payload["Label"], "com.example.test")
        self.assertEqual(payload["StartInterval"], 3600)

    @patch("local_gmail_agent.automation.subprocess.run")
    def test_install_and_uninstall_launch_agent(self, mock_run) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home_dir = Path(temp_dir)
            source_plist = home_dir / "source.plist"
            source_plist.write_text("<plist/>", encoding="utf-8")

            installed_path = install_launch_agent(
                source_plist,
                "default",
                "job123",
                home_dir=home_dir,
            )

            self.assertTrue(installed_path.exists())
            self.assertEqual(
                installed_path,
                installed_launch_agent_path("default", "job123", home_dir=home_dir),
            )

            removed_path = uninstall_launch_agent("default", "job123", home_dir=home_dir)
            self.assertEqual(removed_path, installed_path)
            self.assertFalse(installed_path.exists())

    @patch("local_gmail_agent.automation.subprocess.run")
    def test_is_launch_agent_loaded_uses_launchctl_list(self, mock_run) -> None:
        class Result:
            def __init__(self, returncode: int) -> None:
                self.returncode = returncode

        mock_run.return_value = Result(0)
        self.assertTrue(is_launch_agent_loaded("default", "job123"))
        mock_run.return_value = Result(1)
        self.assertFalse(is_launch_agent_loaded("default", "job123"))


class AutomationStoreTestCase(unittest.TestCase):
    def test_save_list_find_and_remove_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            accounts_root = Path(temp_dir) / "accounts"
            automation_dir = accounts_root / "default" / "automation"
            job = AutomationJob(
                name="Nightly",
                account_name="default",
                query="in:inbox",
                limit=100,
                schedule_type="daily",
                daily_at="01:30",
            )

            save_automation_job(automation_dir, job)
            listed = list_automation_jobs(automation_dir)
            found = find_automation_job(accounts_root, job.id)

            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].id, job.id)
            self.assertIsNotNone(found)

            paths = job_paths(automation_dir, job.id)
            paths.runner_path.parent.mkdir(parents=True, exist_ok=True)
            paths.runner_path.write_text("runner", encoding="utf-8")
            paths.plist_path.write_text("plist", encoding="utf-8")
            paths.reports_dir.mkdir(parents=True, exist_ok=True)
            (paths.reports_dir / "old.md").write_text("report", encoding="utf-8")

            remove_automation_job(automation_dir, job.id)

            self.assertFalse(paths.json_path.exists())
            self.assertFalse(paths.runner_path.exists())
            self.assertFalse(paths.plist_path.exists())


class AutomationCliTestCase(unittest.TestCase):
    @staticmethod
    def _job_id_from_output(output: str) -> str:
        for line in output.splitlines():
            if line.startswith("Job ID: "):
                return line.removeprefix("Job ID: ").strip()
        raise AssertionError(f"Could not find job id in output:\n{output}")

    def test_automation_add_list_and_show(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            env = {"LGA_DATA_DIR": str(data_dir)}

            result = runner.invoke(
                app,
                [
                    "automation",
                    "add",
                    "--name",
                    "Nightly Cleanup",
                    "--daily-at",
                    "01:30",
                    "--limit",
                    "50",
                ],
                env=env,
            )
            self.assertEqual(result.exit_code, 0, result.output)
            job_id = self._job_id_from_output(result.output)

            listed = runner.invoke(app, ["automation", "list"], env=env)
            self.assertEqual(listed.exit_code, 0, listed.output)
            self.assertIn(job_id[:12], listed.output)
            self.assertIn("Nightly Cleanup", listed.output)

            shown = runner.invoke(app, ["automation", "show", "--id", job_id], env=env)
            self.assertEqual(shown.exit_code, 0, shown.output)
            self.assertIn("01:30", shown.output)
            self.assertIn("default", shown.output)

    @patch("local_gmail_agent.cli.install_launch_agent")
    def test_automation_enable_marks_job_enabled(self, mock_install) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            env = {"LGA_DATA_DIR": str(data_dir)}
            mock_install.return_value = Path(temp_dir) / "installed.plist"

            add = runner.invoke(
                app,
                ["automation", "add", "--every-hours", "8"],
                env=env,
            )
            self.assertEqual(add.exit_code, 0, add.output)
            job_id = self._job_id_from_output(add.output)

            enabled = runner.invoke(app, ["automation", "enable", "--id", job_id], env=env)
            self.assertEqual(enabled.exit_code, 0, enabled.output)

            found = find_automation_job(data_dir / "accounts", job_id)
            assert found is not None
            job, _ = found
            self.assertTrue(job.enabled)

    @patch("local_gmail_agent.cli.uninstall_launch_agent")
    def test_automation_disable_marks_job_disabled(self, mock_uninstall) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            env = {"LGA_DATA_DIR": str(data_dir)}
            mock_uninstall.return_value = Path(temp_dir) / "removed.plist"

            add = runner.invoke(
                app,
                ["automation", "add", "--every-hours", "8"],
                env=env,
            )
            self.assertEqual(add.exit_code, 0, add.output)
            job_id = self._job_id_from_output(add.output)

            runner.invoke(app, ["automation", "enable", "--id", job_id], env=env)
            disabled = runner.invoke(app, ["automation", "disable", "--id", job_id], env=env)
            self.assertEqual(disabled.exit_code, 0, disabled.output)

            found = find_automation_job(data_dir / "accounts", job_id)
            assert found is not None
            job, _ = found
            self.assertFalse(job.enabled)

    @patch("local_gmail_agent.cli.is_launch_agent_loaded")
    def test_automation_show_reports_loaded_state(self, mock_loaded) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            env = {"LGA_DATA_DIR": str(data_dir)}
            mock_loaded.return_value = True

            add = runner.invoke(
                app,
                ["automation", "add", "--every-hours", "8"],
                env=env,
            )
            self.assertEqual(add.exit_code, 0, add.output)
            job_id = self._job_id_from_output(add.output)

            shown = runner.invoke(app, ["automation", "show", "--id", job_id], env=env)
            self.assertEqual(shown.exit_code, 0, shown.output)
            self.assertIn("True", shown.output)


if __name__ == "__main__":
    unittest.main()
