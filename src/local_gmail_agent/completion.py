from __future__ import annotations

import os
import shlex
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path


COMMAND_NAME = "local-gmail-agent"
SUPPORTED_SHELLS = ("zsh", "bash", "fish")


@dataclass(frozen=True)
class CompletionInstallResult:
    shell: str
    completion_path: Path
    command_path: Path | None
    command_dir_on_path: bool
    shell_config_path: Path | None
    shell_config_updated: bool


def detect_shell() -> str | None:
    shell = Path(os.environ.get("SHELL", "")).name.lower()
    if shell in SUPPORTED_SHELLS:
        return shell
    return None


def find_project_root(start: Path | None = None) -> Path:
    candidates = []
    if start is not None:
        candidates.extend([start.resolve(), *start.resolve().parents])

    module_path = Path(__file__).resolve()
    candidates.extend(module_path.parents)

    for candidate in candidates:
        pyproject_path = candidate / "pyproject.toml"
        if not pyproject_path.exists():
            continue
        with pyproject_path.open("rb") as file:
            pyproject = tomllib.load(file)
        if pyproject.get("project", {}).get("name") == "local-gmail-agent":
            return candidate

    raise FileNotFoundError("Could not find the local-gmail-agent project root.")


def default_completion_dir(shell: str, home: Path | None = None) -> Path:
    home = home or Path.home()
    if shell == "zsh":
        return home / ".zfunc"
    if shell == "bash":
        return home / ".local" / "share" / "bash-completion" / "completions"
    if shell == "fish":
        return home / ".config" / "fish" / "completions"
    raise ValueError(f"Unsupported shell: {shell}")


def default_shell_config_path(shell: str, home: Path | None = None) -> Path:
    home = home or Path.home()
    if shell == "zsh":
        return home / ".zshrc"
    if shell == "bash":
        return home / ".bashrc"
    if shell == "fish":
        return home / ".config" / "fish" / "config.fish"
    raise ValueError(f"Unsupported shell: {shell}")


def completion_filename(shell: str, command_name: str = COMMAND_NAME) -> str:
    if shell == "zsh":
        return f"_{command_name}"
    if shell == "fish":
        return f"{command_name}.fish"
    if shell == "bash":
        return command_name
    raise ValueError(f"Unsupported shell: {shell}")


def build_uv_command(project_root: Path, command_name: str = COMMAND_NAME) -> str:
    return shlex.join(("uv", "run", "--project", str(project_root), command_name))


def build_completion_script(
    shell: str,
    project_root: Path,
    command_name: str = COMMAND_NAME,
) -> str:
    complete_var = f"_{command_name.replace('-', '_').upper()}_COMPLETE"
    complete_func = f"_{command_name.replace('-', '_')}_completion"
    command = build_uv_command(project_root, command_name)

    if shell == "zsh":
        return f"""#compdef {command_name}

{complete_func}() {{
  eval $(env _TYPER_COMPLETE_ARGS="${{words[1,$CURRENT]}}" {complete_var}=complete_zsh {command})
}}

compdef {complete_func} {command_name}
"""

    if shell == "bash":
        return f"""{complete_func}() {{
    local IFS=$'\\n'
    COMPREPLY=( $( env COMP_WORDS="${{COMP_WORDS[*]}}" \\
                   COMP_CWORD=$COMP_CWORD \\
                   {complete_var}=complete_bash {command} ) )
    return 0
}}

complete -o default -F {complete_func} {command_name}
"""

    if shell == "fish":
        return (
            f"complete --command {command_name} --no-files "
            f'--arguments "(env {complete_var}=complete_fish '
            f"_TYPER_COMPLETE_FISH_ACTION=get-args "
            f"_TYPER_COMPLETE_ARGS=(commandline -cp) {command})\" "
            f'--condition "env {complete_var}=complete_fish '
            f"_TYPER_COMPLETE_FISH_ACTION=is-args "
            f"_TYPER_COMPLETE_ARGS=(commandline -cp) {command}\"\n"
        )

    raise ValueError(f"Unsupported shell: {shell}")


def build_command_wrapper(project_root: Path, command_name: str = COMMAND_NAME) -> str:
    quoted_project_root = shlex.quote(str(project_root))
    return f"""#!/bin/sh
exec uv run --project {quoted_project_root} {command_name} "$@"
"""


def path_contains(directory: Path) -> bool:
    directory = directory.expanduser().resolve()
    for path_entry in os.environ.get("PATH", "").split(os.pathsep):
        if not path_entry:
            continue
        try:
            if Path(path_entry).expanduser().resolve() == directory:
                return True
        except OSError:
            continue
    return False


def build_shell_config_block(
    shell: str,
    completion_dir: Path,
    command_dir: Path | None,
    command_name: str = COMMAND_NAME,
) -> str:
    start_marker = f"# >>> {command_name} completion >>>"
    end_marker = f"# <<< {command_name} completion <<<"
    completion_dir_text = shlex.quote(str(completion_dir))
    command_dir_text = shlex.quote(str(command_dir)) if command_dir is not None else None

    if shell == "zsh":
        lines = [start_marker]
        if command_dir_text is not None:
            lines.append(f"export PATH={command_dir_text}:$PATH")
        lines.extend(
            (
                f"fpath=({completion_dir_text} $fpath)",
                "autoload -Uz compinit",
                "compinit",
                end_marker,
            )
        )
        return "\n".join(lines) + "\n"

    if shell == "bash":
        lines = [start_marker]
        if command_dir_text is not None:
            lines.append(f"export PATH={command_dir_text}:$PATH")
        lines.append(end_marker)
        return "\n".join(lines) + "\n"

    if shell == "fish":
        lines = [start_marker]
        if command_dir_text is not None:
            lines.append(f"fish_add_path {command_dir_text}")
        lines.append(end_marker)
        return "\n".join(lines) + "\n"

    raise ValueError(f"Unsupported shell: {shell}")


def update_shell_config_file(path: Path, block: str, command_name: str = COMMAND_NAME) -> bool:
    start_marker = f"# >>> {command_name} completion >>>"
    end_marker = f"# <<< {command_name} completion <<<"
    path = path.expanduser()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    start_index = existing.find(start_marker)
    end_index = existing.find(end_marker)
    if start_index >= 0 and end_index >= start_index:
        end_index += len(end_marker)
        if end_index < len(existing) and existing[end_index] == "\n":
            end_index += 1
        updated = existing[:start_index] + block + existing[end_index:]
    else:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        updated = existing + separator + block

    if updated == existing:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return True


def install_completion(
    shell: str,
    project_root: Path,
    completion_dir: Path | None = None,
    command_dir: Path | None = None,
    install_command: bool = True,
    update_shell_config: bool = True,
    shell_config_path: Path | None = None,
    force: bool = True,
    command_name: str = COMMAND_NAME,
) -> CompletionInstallResult:
    if shell not in SUPPORTED_SHELLS:
        raise ValueError(f"Unsupported shell: {shell}")

    completion_dir = (completion_dir or default_completion_dir(shell)).expanduser()
    completion_path = completion_dir / completion_filename(shell, command_name)
    if completion_path.exists() and not force:
        raise FileExistsError(f"Completion file already exists: {completion_path}")

    completion_dir.mkdir(parents=True, exist_ok=True)
    completion_path.write_text(
        build_completion_script(shell, project_root, command_name),
        encoding="utf-8",
    )

    command_path = None
    command_dir_on_path = True
    if install_command:
        command_dir = (command_dir or (Path.home() / ".local" / "bin")).expanduser()
        command_path = command_dir / command_name
        if command_path.exists() and not force:
            raise FileExistsError(f"Command wrapper already exists: {command_path}")
        command_dir.mkdir(parents=True, exist_ok=True)
        command_path.write_text(
            build_command_wrapper(project_root, command_name),
            encoding="utf-8",
        )
        command_path.chmod(
            command_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        command_dir_on_path = path_contains(command_dir)

    resolved_shell_config_path = None
    shell_config_updated = False
    if update_shell_config:
        resolved_shell_config_path = (
            shell_config_path or default_shell_config_path(shell)
        ).expanduser()
        shell_config_updated = update_shell_config_file(
            resolved_shell_config_path,
            build_shell_config_block(
                shell=shell,
                completion_dir=completion_dir,
                command_dir=command_dir if install_command else None,
                command_name=command_name,
            ),
            command_name=command_name,
        )
        if install_command and command_dir is not None:
            command_dir_on_path = path_contains(command_dir)

    return CompletionInstallResult(
        shell=shell,
        completion_path=completion_path,
        command_path=command_path,
        command_dir_on_path=command_dir_on_path,
        shell_config_path=resolved_shell_config_path,
        shell_config_updated=shell_config_updated,
    )
