from enum import StrEnum
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunMode(StrEnum):
    MANUAL_SEED = "MANUAL_SEED"
    AUTO = "AUTO"


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: RunMode
    seed_text: str | None = None

    @model_validator(mode="after")
    def validate_mode_input(self) -> "RunCreate":
        if self.mode is RunMode.MANUAL_SEED:
            if self.seed_text is None or not self.seed_text.strip():
                raise ValueError("MANUAL_SEED requires a nonblank seed_text")
            self.seed_text = self.seed_text.strip()
        elif self.seed_text is not None:
            raise ValueError("AUTO forbids seed_text")
        return self


class RunAccepted(BaseModel):
    run_id: str
    status: str


class RunArtifact(BaseModel):
    title: str
    text: str


class RunTokenUsage(BaseModel):
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int
    finalized: bool


class RunError(BaseModel):
    code: str
    message: str


class RunStatus(BaseModel):
    run_id: str
    mode: str
    status: str
    elapsed_seconds: int
    started_at: datetime | None
    finished_at: datetime | None
    latest_activity: str
    token_usage: RunTokenUsage
    original_meme: RunArtifact | None
    template: str | None
    formal_meme: RunArtifact | None
    error: RunError | None
    stop_reason: str | None


class EvaluationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, strict=True)


class EvaluationResult(BaseModel):
    run_id: str
    score: int
    evaluation_status: str
    dynamic_example_eligible: bool


class FormalMemeItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_run_id: str
    original_title: str
    original_text: str
    final_title: str
    final_text: str
    score: int
    evaluation_status: str
    dynamic_example_eligible: bool
    created_at: datetime


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class FormalMemePage(BaseModel):
    items: list[FormalMemeItem]
    pagination: Pagination


class DynamicExample(BaseModel):
    original_title: str
    original_text: str
    final_title: str
    final_text: str
    score: int
