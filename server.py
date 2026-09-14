import argparse
from typing import Literal

from mcp.server import MCPServer

from executor import execute_task

SERVER_INSTRUCTIONS = """Use this server only for bounded coding work in a user-selected clean local Git repository. The caller owns planning and the explicit file and test scope. delegate_task sends that scope to the configured worker model; local code applies proposed edits in an isolated worktree and returns actual tests and git diff. Treat completion as pending Sol review. Do not merge or copy changes until Sol reviews git_diff. If needs_escalation is true, stop this delegated task and return its reason."""

mcp = MCPServer("codex-agent-workers", instructions=SERVER_INSTRUCTIONS)


@mcp.tool()
def delegate_task(
    task: str,
    repo_path: str,
    files: list[str],
    context: str,
    acceptance_criteria: list[str],
    difficulty: Literal["fast", "hard"] = "fast",
    test_commands: list[list[str]] | None = None,
    test_timeout_seconds: int = 120,
) -> dict:
    """Execute one bounded coding task in an isolated local git worktree.

    The orchestrator supplies the task and explicit file scope. The model proposes
    structured edits. Local code validates and applies them, runs allowlisted test
    commands without a shell, and returns the real git diff for Sol review.
    """

    return execute_task(
        task=task,
        repo_path=repo_path,
        files=files,
        context=context,
        acceptance_criteria=acceptance_criteria,
        difficulty=difficulty,
        test_commands=test_commands or [],
        test_timeout_seconds=test_timeout_seconds,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true", help="serve Streamable HTTP on localhost")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.http:
        mcp.run(transport="streamable-http", host="127.0.0.1", port=args.port)
    else:
        mcp.run()
