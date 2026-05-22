from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from local_gmail_agent.automation import parse_daily_time


class AutomationJob(BaseModel):
    version: int = 1
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    account_name: str
    query: str
    limit: int = Field(ge=1)
    apply: bool = True
    reprocess: bool = False
    schedule_type: str
    every_hours: int | None = Field(default=None, ge=1)
    daily_at: str | None = None
    start_lm_studio: bool = True
    lm_studio_app: str = "LM Studio"
    wait_seconds: int = Field(default=120, ge=5)
    enabled: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _normalize(self) -> "AutomationJob":
        self.id = self.id.strip().lower()
        self.name = self.name.strip() or self.id
        self.account_name = self.account_name.strip()
        self.query = self.query.strip()
        self.schedule_type = self.schedule_type.strip().lower()
        self.lm_studio_app = self.lm_studio_app.strip() or "LM Studio"
        self.updated_at = self.updated_at.astimezone(UTC)
        self.created_at = self.created_at.astimezone(UTC)

        if self.schedule_type not in {"interval", "daily"}:
            raise ValueError("schedule_type must be 'interval' or 'daily'.")

        if self.schedule_type == "interval":
            if self.every_hours is None:
                raise ValueError("every_hours is required for interval schedules.")
            self.daily_at = None
        else:
            if self.daily_at is None:
                raise ValueError("daily_at is required for daily schedules.")
            hour, minute = parse_daily_time(self.daily_at)
            self.daily_at = f"{hour:02d}:{minute:02d}"
            self.every_hours = None

        return self

    @property
    def schedule_description(self) -> str:
        if self.schedule_type == "interval":
            assert self.every_hours is not None
            return f"every {self.every_hours}h"
        assert self.daily_at is not None
        return f"daily {self.daily_at}"


class AutomationJobPaths(BaseModel):
    json_path: Path
    runner_path: Path
    plist_path: Path
    stdout_log_path: Path
    stderr_log_path: Path
    reports_dir: Path
    latest_report_path: Path


def job_paths(automation_dir: Path, job_id: str) -> AutomationJobPaths:
    jobs_dir = automation_dir / "jobs"
    reports_dir = automation_dir / "reports" / job_id
    logs_dir = automation_dir / "logs"
    return AutomationJobPaths(
        json_path=jobs_dir / f"{job_id}.json",
        runner_path=jobs_dir / f"{job_id}.sh",
        plist_path=jobs_dir / f"{job_id}.plist",
        stdout_log_path=logs_dir / f"{job_id}.stdout.log",
        stderr_log_path=logs_dir / f"{job_id}.stderr.log",
        reports_dir=reports_dir,
        latest_report_path=reports_dir / "latest.md",
    )


def save_automation_job(automation_dir: Path, job: AutomationJob) -> Path:
    paths = job_paths(automation_dir, job.id)
    paths.json_path.parent.mkdir(parents=True, exist_ok=True)
    paths.json_path.write_text(job.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return paths.json_path


def load_automation_job(path: Path) -> AutomationJob:
    return AutomationJob.model_validate_json(path.read_text(encoding="utf-8"))


def list_automation_jobs(automation_dir: Path) -> list[AutomationJob]:
    jobs_dir = automation_dir / "jobs"
    if not jobs_dir.exists():
        return []
    jobs: list[AutomationJob] = []
    for path in sorted(jobs_dir.glob("*.json")):
        jobs.append(load_automation_job(path))
    return jobs


def remove_automation_job(automation_dir: Path, job_id: str) -> AutomationJobPaths:
    paths = job_paths(automation_dir, job_id)
    for path in (
        paths.json_path,
        paths.runner_path,
        paths.plist_path,
        paths.stdout_log_path,
        paths.stderr_log_path,
        paths.latest_report_path,
    ):
        if path.exists():
            path.unlink()
    if paths.reports_dir.exists():
        remaining = list(paths.reports_dir.iterdir())
        for item in remaining:
            item.unlink()
        paths.reports_dir.rmdir()
    return paths


def find_automation_job(accounts_root: Path, job_id: str) -> tuple[AutomationJob, Path] | None:
    for path in sorted(accounts_root.glob(f"*/automation/jobs/{job_id}.json")):
        return load_automation_job(path), path
    return None
