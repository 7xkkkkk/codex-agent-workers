import subprocess
import os
import tempfile
import unittest
from pathlib import Path

from schemas import FileEdit
from workspace import (
    WorkspaceError,
    _repo_path_for_runtime,
    apply_edits,
    collect_diff,
    create_worktree,
    load_files,
    validate_repo,
)


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.old_worktree_root = os.environ.get("CODEX_WORKER_WORKTREE_ROOT")
        os.environ["CODEX_WORKER_WORKTREE_ROOT"] = str(Path(self.temp.name) / "worktrees")
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "executor@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Executor Test"], check=True)
        (self.repo / "app.py").write_text("value = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "app.py"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "initial"], check=True)

    def tearDown(self) -> None:
        subprocess.run(["git", "-C", str(self.repo), "worktree", "prune"], check=False)
        if self.old_worktree_root is None:
            os.environ.pop("CODEX_WORKER_WORKTREE_ROOT", None)
        else:
            os.environ["CODEX_WORKER_WORKTREE_ROOT"] = self.old_worktree_root
        self.temp.cleanup()

    def test_load_files_rejects_escape(self) -> None:
        repo = validate_repo(str(self.repo))
        self.assertIn("FILE: app.py", load_files(repo, ["app.py"]))
        with self.assertRaises(WorkspaceError):
            load_files(repo, ["../outside.py"])

    def test_windows_repo_path_maps_to_wsl_mount(self) -> None:
        if os.name == "posix":
            self.assertEqual(
                _repo_path_for_runtime(r"C:\Users\example\repo"),
                Path("/mnt/c/Users/example/repo"),
            )

    def test_exact_edit_is_applied_in_isolated_worktree(self) -> None:
        repo = validate_repo(str(self.repo))
        worktree = create_worktree(repo)
        apply_edits(
            worktree,
            [FileEdit(path="app.py", action="replace", old_content="value = 1", new_content="value = 2")],
        )
        changed, diff = collect_diff(worktree)
        self.assertEqual(changed, ["app.py"])
        self.assertIn("+value = 2", diff)
        self.assertEqual((self.repo / "app.py").read_text(encoding="utf-8"), "value = 1\n")

    def test_ambiguous_edit_is_rejected_before_write(self) -> None:
        (self.repo / "app.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "app.py"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "duplicate"], check=True)
        worktree = create_worktree(validate_repo(str(self.repo)))
        with self.assertRaises(WorkspaceError):
            apply_edits(worktree, [FileEdit(path="app.py", action="replace", old_content="x = 1", new_content="x = 2")])
        self.assertEqual((worktree / "app.py").read_text(encoding="utf-8"), "x = 1\nx = 1\n")


if __name__ == "__main__":
    unittest.main()
