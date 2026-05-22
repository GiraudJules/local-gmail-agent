from __future__ import annotations

import logging as pylogging
from pathlib import Path

from rich.logging import RichHandler

from local_gmail_agent.schemas import DecisionLogEntry


def configure_logging(verbose: bool = False) -> pylogging.Logger:
    pylogging.basicConfig(
        level=pylogging.DEBUG if verbose else pylogging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                show_path=verbose,
                rich_tracebacks=True,
                markup=True,
            )
        ],
        force=True,
    )
    return pylogging.getLogger("local_gmail_agent")


class DecisionLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: DecisionLogEntry) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json())
            handle.write("\n")
