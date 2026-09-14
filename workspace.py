from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path, PurePosixPath

from schemas import FileEdit, TestRun

ALLOWED_TESTS = {
    "pytest": lambda args: True,
    "python": lambda args: len(args) >= 2 and args[0] == "-m" and args[1] in {"pytest", "unittest"},
    "python3": lambda args: len(args) >= 2 and args[0] == "-m" and args[1] in {"pytest", "unittest"},
    "npm": lambda args: args == ["test"] or args[:2] == ["run", "test"],
    "pnpm": lambda args: args == ["test"],
    "yarn": lambda args: args == ["test"],
    "cargo": lambda args: bool(args) and args[0] == "test",
    "go": lambda args: bool(args) and args[0] == "test",
}


class WorkspaceError(RuntimeError):
    pass


def _git(repo: Path, *args: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkspaceError(f"git failed: {exc}") from exc
    if result.returncode:
        raise WorkspaceError(result.stdout.strip() or "git failed")
    return result.stdout


def _repo_path_for_runtime(repo_path: str) -> Path:
    if (
        os.name == "posix"
        and len(repo_path) >= 3
        and repo_path[0].isalpha()
        and repo_path[1] == ":"
        and repo_path[2] in {"\\", "/"}
    ):
        relative = PurePosixPath(repo_path[3:].replace("\\", "/"))
        return Path("/mnt") / repo_path[0].lower() / relative
    return Path(repo_path)


def validate_repo(repo_path: str) -> Path:
    repo = _repo_path_for_runtime(repo_path).expanduser().resolve()
    if not repo.is_dir():
        raise WorkspaceError("repo_path must be an existing directory")
    root = Path(_git(repo, "rev-parse", "--show-toplevel").strip()).resolve()
    if root != repo:
        raise WorkspaceError(f"repo_path must be the repository root: {root}")
    if _git(repo, "status", "--porcelain=v1", "--untracked-files=all").strip():
        raise WorkspaceError("repository must be clean before creating an isolated worktree")
    return repo


def _path_in(repo: Path, value: str, *, must_exist: bool) -> Path:
    relative = PurePosixPath(value)
    if not value or "\\" in value or relative.is_absolute() or ".." in relative.parts:
        raise WorkspaceError(f"invalid repository-relative path: {value!r}")
    if relative.parts[0] == ".git":
        raise WorkspaceError(".git is not part of the editable repository content")
    path = repo.joinpath(*relative.parts)
    resolved = path.resolve(strict=must_exist)
    try:
        resolved.relative_to(repo)
    except ValueError as exc:
        raise WorkspaceError(f"path escapes repository: {value}") from exc
    return path


def load_files(repo: Path, files: list[str]) -> str:
    if not files:
        raise WorkspaceError("files cannot be empty")
    sections = []
    for value in files:
        path = _path_in(repo, value, must_exist=True)
        if not path.is_file():
            raise WorkspaceError(f"not a file: {value}")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceError(f"file is not UTF-8 text: {value}") from exc
        sections.append(f"FILE: {value}\n```text\n{content}\n```")
    return "\n\n".join(sections)


def create_worktree(repo: Path) -> Path:
    root = Path(os.getenv("CODEX_WORKER_WORKTREE_ROOT", "~/.local/share/codex-agent-workers/worktrees"))
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    worktree = root / f"{repo.name}-{uuid.uuid4().hex[:12]}"
    _git(repo, "worktree", "add", "--detach", str(worktree), "HEAD", timeout=60)
    return worktree


def apply_edits(worktree: Path, edits: list[FileEdit]) -> None:
    if not edits:
        raise WorkspaceError("worker returned no edits")
    if len({edit.path for edit in edits}) != len(edits):
        raise WorkspaceError("worker returned multiple edits for one file")

    planned: list[tuple[Path, str]] = []
    for edit in edits:
        path = _path_in(worktree, edit.path, must_exist=edit.action == "replace")
        if edit.action == "create":
            if path.exists():
                raise WorkspaceError(f"file already exists: {edit.path}")
            content = edit.new_content
        else:
            current = path.read_text(encoding="utf-8")
            matches = current.count(edit.old_content or "")
            if matches != 1:
                raise WorkspaceError(f"old_content matched {matches} times in {edit.path}")
            content = current.replace(edit.old_content or "", edit.new_content, 1)
        planned.append((path, content))

    for path, content in planned:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _check_test_command(command: list[str]) -> None:
    if not command:
        raise WorkspaceError("test command cannot be empty")
    executable, args = command[0], command[1:]
    if executable not in ALLOWED_TESTS or not ALLOWED_TESTS[executable](args):
        raise WorkspaceError(f"test command is not allowed: {command!r}")


def run_tests(worktree: Path, commands: list[list[str]], timeout_seconds: int) -> list[TestRun]:
    results = []
    timeout_seconds = max(1, min(timeout_seconds, 600))
    for command in commands:
        _check_test_command(command)
        executable = sys.executable if command[0] in {"python", "python3"} else shutil.which(command[0])
        if not executable:
            raise WorkspaceError(f"test executable is unavailable: {command[0]}")
        with tempfile.TemporaryDirectory(prefix="codex-worker-test-") as temp_home:
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": temp_home,
                "TMPDIR": temp_home,
                "LANG": os.environ.get("LANG", "C.UTF-8"),
                "CI": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            try:
                run = subprocess.run(
                    [executable, *command[1:]],
                    cwd=worktree,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=timeout_seconds,
                    check=False,
                )
                results.append(TestRun(command=command, exit_code=run.returncode, output=run.stdout[-40_000:]))
            except subprocess.TimeoutExpired as exc:
                output = exc.stdout or ""
                if isinstance(output, bytes):
                    output = output.decode("utf-8", errors="replace")
                results.append(TestRun(command=command, exit_code=None, output=output[-40_000:], timed_out=True))
        if results[-1].exit_code != 0:
            break
    return results


def collect_diff(worktree: Path) -> tuple[list[str], str]:
    status = _git(worktree, "status", "--porcelain=v1", "--untracked-files=all")
    for line in status.splitlines():
        if line.startswith("?? "):
            _git(worktree, "add", "--intent-to-add", "--", line[3:])
    changed = _git(worktree, "diff", "--name-only", "--").splitlines()
    diff = _git(worktree, "diff", "--no-ext-diff", "--binary", "--")
    return sorted(set(changed)), diff
