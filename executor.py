from providers.openai_compatible import model_for_difficulty, propose_patch
from schemas import ExecutionResult
from workspace import (
    WorkspaceError,
    apply_edits,
    collect_diff,
    create_worktree,
    load_files,
    run_tests,
    validate_repo,
)


def execute_task(
    task: str,
    repo_path: str,
    files: list[str],
    context: str,
    acceptance_criteria: list[str],
    difficulty: str,
    test_commands: list[list[str]],
    test_timeout_seconds: int,
) -> dict:
    worker = ""
    worktree = None
    try:
        worker = model_for_difficulty(difficulty)
        repo = validate_repo(repo_path)
        repository_context = load_files(repo, files)
        worker, proposal = propose_patch(
            task=task,
            repository_context=repository_context,
            context=context,
            acceptance_criteria=acceptance_criteria,
            difficulty=difficulty,
        )
        if proposal.needs_escalation or not proposal.edits:
            reason = proposal.escalation_reason or "worker returned no executable edits"
            return ExecutionResult(
                worker=worker,
                status="blocked",
                summary=proposal.summary,
                uncertainties=proposal.uncertainties,
                needs_escalation=True,
                escalation_reason=reason,
            ).model_dump()

        worktree = create_worktree(repo)
        apply_edits(worktree, proposal.edits)
        tests = run_tests(worktree, test_commands, test_timeout_seconds)
        changed_files, git_diff = collect_diff(worktree)
        tests_passed = all(run.exit_code == 0 and not run.timed_out for run in tests)
        if test_commands and not tests_passed:
            status = "incomplete"
            needs_escalation = True
            escalation_reason = "one or more controlled test commands failed or timed out"
        else:
            status = "completed"
            needs_escalation = False
            escalation_reason = None
        return ExecutionResult(
            worker=worker,
            status=status,
            summary=proposal.summary,
            changed_files=changed_files,
            tests_run=tests,
            git_diff=git_diff,
            worktree_path=str(worktree),
            uncertainties=proposal.uncertainties,
            needs_escalation=needs_escalation,
            escalation_reason=escalation_reason,
        ).model_dump()
    except (WorkspaceError, RuntimeError, ValueError) as exc:
        return ExecutionResult(
            worker=worker,
            status="blocked",
            summary="The local executor could not safely complete the task.",
            worktree_path=str(worktree) if worktree else None,
            needs_escalation=True,
            escalation_reason=str(exc),
        ).model_dump()
