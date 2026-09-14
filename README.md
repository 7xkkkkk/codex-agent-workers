# codex-agent-workers

[English](README.md) | [简体中文](README.zh-CN.md)

A local MCP server that turns a bounded coding task into a reviewable Git diff.
Your coding assistant chooses the task, files and tests. A configured worker model
proposes edits; the executor applies them in a detached Git worktree, runs the
requested tests and returns the actual results.

API credentials, base URL and model names are configurable. Both OpenAI-compatible
Chat Completions and Responses endpoints are supported. This project is not tied
to a particular API vendor and is not an official OpenAI product.

## Requirements

- Python 3.12 and Git, available to the server process.
- Linux or WSL, the tested execution environments.
- An API endpoint supporting one of the two protocols and a model that can return
  the requested JSON edit format.
- A target Git repository with at least one commit and a clean working tree.

Git works entirely locally. GitHub hosting is not required for target repositories.

## Setup

Clone or download this repository, then run:

```bash
cd codex-agent-workers
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your provider's values:

```dotenv
WORKER_BASE_URL=https://api.example.com/v1
WORKER_API_KEY=your-api-key
WORKER_MODEL_FAST=your-fast-model
WORKER_MODEL_HARD=your-reasoning-model
WORKER_API_MODE=chat_completions
```

`api.example.com` is a placeholder. Use the exact API base URL documented by your
provider, including `/v1` if required. Use `responses` for a Responses-compatible
endpoint. Both model variables may name the same model. `.env` is loaded beside
`server.py`, regardless of the client's working directory; existing environment
variables take precedence. Never commit real credentials.

## Connect an MCP client

The default transport is stdio:

```bash
.venv/bin/python server.py
```

Configure your client to launch the virtual environment's Python with an absolute
path to `server.py`. For clients using the `mcpServers` JSON convention:

```json
{
  "mcpServers": {
    "codex-agent-workers": {
      "command": "/absolute/path/codex-agent-workers/.venv/bin/python",
      "args": ["/absolute/path/codex-agent-workers/server.py"]
    }
  }
}
```

For a Windows client and a WSL server, an optional local HTTP transport is available:

```bash
.venv/bin/python server.py --http --port 8765
```

Connect to `http://127.0.0.1:8765/mcp`. Keep the server terminal running. After a
server restart, reconnect the client to establish a new session. HTTP binds to
loopback and has no authentication; it is for local use only.

## Delegate a task

Call `delegate_task` with explicit inputs:

```json
{
  "task": "Make status() return ready.",
  "repo_path": "/absolute/path/target-repo",
  "files": ["main.py", "test_main.py"],
  "context": "Keep the existing function signature.",
  "acceptance_criteria": ["The existing status test passes."],
  "difficulty": "fast",
  "test_commands": [["python", "-m", "unittest", "-q"]],
  "test_timeout_seconds": 120
}
```

`difficulty` selects `WORKER_MODEL_FAST` or `WORKER_MODEL_HARD`. File paths use `/`
and are relative to the repository root. On WSL with standard drive mounts,
Windows paths such as `C:\projects\target-repo` map to `/mnt/c/projects/target-repo`.
For custom mounts, pass the actual Linux path. UNC paths are not translated.

The response includes `worker`, `status`, `changed_files`, `tests_run`, `git_diff`,
`worktree_path`, `needs_escalation` and `escalation_reason`. Status is `completed`,
`incomplete` or `blocked`. An empty `tests_run` means no tests ran. Completion does
not mean the changes have been reviewed or merged.

The current review contract returns `review_required: true` and `review_role: sol`.
The caller owns orchestration and must arrange that review; the server does not
call a reviewer automatically. Changes stay in the returned worktree for inspection.

```bash
git -C /returned/worktree/path diff
# After reviewing and saving the result, discard the temporary worktree:
git -C /absolute/path/target-repo worktree remove --force /returned/worktree/path
```

Worktrees default to `~/.local/share/codex-agent-workers/worktrees`. Override this
with `CODEX_WORKER_WORKTREE_ROOT` if needed.

## Boundaries

Selected file contents, task, context and acceptance criteria are sent to the
configured API. Target files are not automatically scrubbed of secrets: choose
files suitable for that provider. `.gitignore` controls version control, not the
explicit `files` input.

Edits use exact `create` / `replace` operations. The executor rejects path escapes,
ambiguous replacements and dirty repositories. Tests use argv arrays without a
shell. The allowlist covers pytest, Python unittest/pytest, npm test, pnpm test,
yarn test, cargo test and go test. Timeouts are capped at 600 seconds. Install the
target project's test dependencies in the server environment as needed.

A Git worktree isolates file changes, **not operating-system access**. Tests run
repository code with the server user's permissions. Use repositories you trust.
The OpenAI client library's retry behavior is unchanged; the executor adds no
automatic recovery loop or retry framework.

## Troubleshooting

- **Not a Git repository:** initialize the intended source folder, select the
  files to track and make an initial commit. Exclude credentials and runtime data.
- **Repository must be clean:** inspect `git status` in the server environment
  and resolve the intended changes before delegating.
- **Directory does not exist:** the path must be accessible to the server process.
- **Model or key not configured:** fill in `.env` using `.env.example`.
- **Provider errors or invalid JSON:** check the base URL, API mode, model support
  and provider response. Protocol compatibility varies by provider.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The suite uses temporary local Git repositories and mocked API responses. It does
not require a key or make paid API calls. Live provider calls are separate from
this regression suite. Licensed under MIT; see [LICENSE](LICENSE).
