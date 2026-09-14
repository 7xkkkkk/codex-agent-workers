import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from schemas import PatchProposal

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

def model_for_difficulty(difficulty: str) -> str:
    variable = {"fast": "WORKER_MODEL_FAST", "hard": "WORKER_MODEL_HARD"}[difficulty]
    model = os.getenv(variable)
    if not model:
        raise RuntimeError(f"{variable} is not configured")
    return model


def _client() -> OpenAI:
    api_key = os.getenv("WORKER_API_KEY")
    if not api_key:
        raise RuntimeError("WORKER_API_KEY is not configured")
    base_url = os.getenv("WORKER_BASE_URL")
    if not base_url:
        raise RuntimeError("WORKER_BASE_URL is not configured")
    return OpenAI(api_key=api_key, base_url=base_url)


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


def propose_patch(
    task: str,
    repository_context: str,
    context: str,
    acceptance_criteria: list[str],
    difficulty: str,
) -> tuple[str, PatchProposal]:
    """Ask the configured model for edits; local code performs side effects."""

    model = model_for_difficulty(difficulty)
    schema = json.dumps(PatchProposal.model_json_schema(), ensure_ascii=False)
    criteria = "\n".join(f"- {item}" for item in acceptance_criteria)
    prompt = f"""TASK
{task}

PROJECT CONTEXT
{context}

ACCEPTANCE CRITERIA
{criteria}

REPOSITORY FILES
{repository_context}

You are the implementation worker. The caller owns planning, repository access,
patch application, tests, and review. Propose only the smallest edits required.

Rules:
- Use only repository-relative paths present above, except for a necessary new file.
- For a replacement, copy old_content exactly from the supplied file and keep it
  as small and unique as possible. The local executor rejects non-unique matches.
- Do not claim that files changed or tests ran.
- Do not alter unrelated behavior or add dependencies unless the task requires it.
- If the supplied files are insufficient, return needs_escalation=true and no edits.
- Return JSON only, matching this JSON Schema:

{schema}
"""

    api_mode = os.getenv("WORKER_API_MODE", "chat_completions")
    if api_mode == "responses":
        response = _client().responses.create(model=model, input=prompt)
        raw = response.output_text
    elif api_mode == "chat_completions":
        response = _client().chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}]
        )
        raw = response.choices[0].message.content or ""
    else:
        raise RuntimeError("WORKER_API_MODE must be chat_completions or responses")
    proposal = PatchProposal.model_validate_json(_strip_code_fence(raw))
    return model, proposal
