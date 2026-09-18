from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


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


class DynamicExample(BaseModel):
    original_title: str
    original_text: str
    final_title: str
    final_text: str

