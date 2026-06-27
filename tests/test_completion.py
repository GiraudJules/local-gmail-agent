from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from typer.testing import CliRunner

from local_gmail_agent.cli import app
from local_gmail_agent.completion import (
    build_completion_script,
    install_completion,
    update_shell_config_file,
)


class CompletionInstallerTestCase(unittest.TestCase):
    def test_zsh_completion_uses_repo_aware_uv_command(self) -> None:
        project_root = Path("/tmp/local-gmail-agent")

        script = build_completion_script("zsh", project_root)

        self.assertIn("#compdef local-gmail-agent", script)
        self.assertIn("_LOCAL_GMAIL_AGENT_COMPLETE=complete_zsh", script)
        self.assertIn("uv run --project /tmp/local-gmail-agent local-gmail-agent", script)

    def test_install_completion_writes_completion_and_command_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "repo"
            completion_dir = root / "completion"
            command_dir = root / "bin"
            shell_config_path = root / ".zshrc"
            project_root.mkdir()

            with mock.patch.dict(os.environ, {"PATH": str(command_dir)}):
                result = install_completion(
                    shell="zsh",
                    project_root=project_root,
                    completion_dir=completion_dir,
                    command_dir=command_dir,
                    shell_config_path=shell_config_path,
                )

            self.assertEqual(result.completion_path, completion_dir / "_local-gmail-agent")
            self.assertEqual(result.command_path, command_dir / "local-gmail-agent")
            self.assertTrue(result.command_dir_on_path)
            self.assertEqual(result.shell_config_path, shell_config_path)
            self.assertTrue(result.shell_config_updated)
            self.assertIn("complete_zsh", result.completion_path.read_text(encoding="utf-8"))
            wrapper = result.command_path.read_text(encoding="utf-8")
            self.assertIn(f"uv run --project {project_root}", wrapper)
            shell_config = shell_config_path.read_text(encoding="utf-8")
            self.assertIn(f"export PATH={command_dir}:$PATH", shell_config)
            self.assertIn(f"fpath=({completion_dir} $fpath)", shell_config)
            self.assertTrue(result.command_path.stat().st_mode & stat.S_IXUSR)

    def test_update_shell_config_replaces_existing_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".zshrc"
            first_block = "# >>> local-gmail-agent completion >>>\nold\n# <<< local-gmail-agent completion <<<\n"
            second_block = "# >>> local-gmail-agent completion >>>\nnew\n# <<< local-gmail-agent completion <<<\n"
            path.write_text(f"before\n{first_block}after\n", encoding="utf-8")

            changed = update_shell_config_file(path, second_block)

            self.assertTrue(changed)
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                f"before\n{second_block}after\n",
            )

    def test_cli_completion_show_accepts_explicit_project_root(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            result = runner.invoke(
                app,
                ["completion", "show", "--shell", "zsh", "--project-root", str(project_root)],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("_LOCAL_GMAIL_AGENT_COMPLETE=complete_zsh", result.output)
        self.assertIn(f"uv run --project {project_root.resolve()}", result.output)

    def test_cli_completion_install_uses_temp_directories(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            completion_dir = root / "completion"
            command_dir = root / "bin"
            shell_config_path = root / ".zshrc"
            result = runner.invoke(
                app,
                [
                    "completion",
                    "install",
                    "--shell",
                    "zsh",
                    "--project-root",
                    str(root),
                    "--completion-dir",
                    str(completion_dir),
                    "--command-dir",
                    str(command_dir),
                    "--shell-config",
                    str(shell_config_path),
                ],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue((completion_dir / "_local-gmail-agent").exists())
            self.assertTrue((command_dir / "local-gmail-agent").exists())
            self.assertTrue(shell_config_path.exists())
            self.assertIn("Installed zsh completion", result.output)
            self.assertIn("Updated shell startup file", result.output)


if __name__ == "__main__":
    unittest.main()
