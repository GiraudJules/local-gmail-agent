from __future__ import annotations

import plistlib
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx


def launchd_label_for_job(account_name: str, job_id: str) -> str:
    return f"com.local_gmail_agent.{account_name}.{job_id}"


def user_launch_agents_dir(home_dir: Path | None = None) -> Path:
    base = home_dir or Path.home()
    return base / "Library" / "LaunchAgents"


def installed_launch_agent_path(
    account_name: str,
    job_id: str,
    home_dir: Path | None = None,
) -> Path:
    return user_launch_agents_dir(home_dir) / f"{launchd_label_for_job(account_name, job_id)}.plist"


def parse_daily_time(value: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("Expected daily time in HH:MM format.")

    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("Daily time must be between 00:00 and 23:59.")
    return hour, minute


def build_runner_script(
    working_directory: Path,
    command: list[str],
) -> str:
    return (
        "#!/bin/zsh\n"
        "set -euo pipefail\n\n"
        f"cd {shlex.quote(str(working_directory))}\n"
        f"{shlex.join(command)}\n"
    )


def build_launchd_plist(
    label: str,
    script_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    start_interval_seconds: int | None = None,
    start_calendar_time: tuple[int, int] | None = None,
) -> str:
    payload: dict[str, object] = {
        "Label": label,
        "ProgramArguments": [str(script_path)],
        "RunAtLoad": True,
        "StandardOutPath": str(stdout_path),
        "StandardErrorPath": str(stderr_path),
        "ProcessType": "Background",
    }
    if start_interval_seconds is not None:
        payload["StartInterval"] = start_interval_seconds
    if start_calendar_time is not None:
        payload["StartCalendarInterval"] = {
            "Hour": start_calendar_time[0],
            "Minute": start_calendar_time[1],
        }
    return plistlib.dumps(payload).decode("utf-8")


def ensure_lm_studio_ready(
    base_url: str,
    app_name: str,
    timeout_seconds: int,
    autostart: bool,
) -> None:
    models_url = f"{base_url.rstrip('/')}/models"
    deadline = time.monotonic() + timeout_seconds

    if autostart and sys.platform == "darwin":
        subprocess.run(["open", "-a", app_name], check=False)

    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(models_url, timeout=5.0)
            response.raise_for_status()
            return
        except Exception as exc:  # pragma: no cover - network timing path
            last_error = str(exc)
            time.sleep(2)

    raise RuntimeError(
        f"LM Studio was not ready at {models_url} within {timeout_seconds}s. "
        f"Last error: {last_error or 'unknown'}"
    )


def install_launch_agent(
    source_plist: Path,
    account_name: str,
    job_id: str,
    home_dir: Path | None = None,
) -> Path:
    destination = installed_launch_agent_path(account_name, job_id, home_dir=home_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_plist, destination)
    subprocess.run(["launchctl", "unload", str(destination)], check=False)
    subprocess.run(["launchctl", "load", str(destination)], check=True)
    return destination


def uninstall_launch_agent(
    account_name: str,
    job_id: str,
    home_dir: Path | None = None,
) -> Path:
    destination = installed_launch_agent_path(account_name, job_id, home_dir=home_dir)
    subprocess.run(["launchctl", "unload", str(destination)], check=False)
    if destination.exists():
        destination.unlink()
    return destination


def is_launch_agent_loaded(account_name: str, job_id: str) -> bool:
    if sys.platform != "darwin":
        return False

    launchctl = shutil.which("launchctl")
    if launchctl is None:
        return False

    result = subprocess.run(
        [launchctl, "list", launchd_label_for_job(account_name, job_id)],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0
