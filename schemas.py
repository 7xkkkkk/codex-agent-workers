from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FileEdit(BaseModel):
    """One exact, locally verifiable file edit proposed by a worker model."""

    path: str
    action: Literal["create", "replace"]
    old_content: str | None = None
    new_content: str

    @model_validator(mode="after")
    def validate_action_fields(self) -> "FileEdit":
        if self.action == "replace" and not self.old_content:
            raise ValueError("replace edits require non-empty old_content")
        if self.action == "create" and self.old_content is not None:
            raise ValueError("create edits must not include old_content")
        return self


class PatchProposal(BaseModel):
    summary: str
    edits: list[FileEdit] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    needs_escalation: bool = False
    escalation_reason: str | None = None


class TestRun(BaseModel):
    command: list[str]
    exit_code: int | None
    output: str
    timed_out: bool = False


class ExecutionResult(BaseModel):
    worker: str
    status: Literal["completed", "incomplete", "blocked"]
    summary: str
    changed_files: list[str] = Field(default_factory=list)
    tests_run: list[TestRun] = Field(default_factory=list)
    git_diff: str = ""
    worktree_path: str | None = None
    uncertainties: list[str] = Field(default_factory=list)
    needs_escalation: bool = False
    escalation_reason: str | None = None
    review_required: bool = True
    review_role: Literal["sol"] = "sol"
