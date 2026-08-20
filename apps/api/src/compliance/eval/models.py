from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class EvaluationCase(BaseModel):
    case_id: str = Field(pattern=r"^eval-\d{2}$")
    question: str = Field(min_length=1)
    reference_answer: str = Field(min_length=1)
    ground_truth_clause_ids: list[str]
    should_refuse: bool = False
    suites: list[Literal["ci", "full"]] = Field(min_length=1)

    @model_validator(mode="after")
    def refusal_has_no_citations(self) -> "EvaluationCase":
        if self.should_refuse == bool(self.ground_truth_clause_ids):
            raise ValueError("refusals must omit clause ids and answered cases must include them")
        return self


class EvaluationDataset(BaseModel):
    cases: list[EvaluationCase]


class EvaluationObservation(BaseModel):
    case_id: str
    response: str
    retrieved_clause_ids: list[str]
    retrieved_contexts: list[str]


class EvaluationScores(BaseModel):
    faithfulness: float = Field(ge=0.0, le=1.0)
    answer_relevance: float = Field(ge=0.0, le=1.0)
    context_precision: float = Field(ge=0.0, le=1.0)
    context_recall: float = Field(ge=0.0, le=1.0)

    @property
    def lowest(self) -> float:
        return min(
            self.faithfulness,
            self.answer_relevance,
            self.context_precision,
            self.context_recall,
        )


class EvaluationResult(BaseModel):
    observation: EvaluationObservation
    scores: EvaluationScores


class EvaluationSnapshot(BaseModel):
    generated_at: datetime
    judge_model: str
    commit_sha: str
    results: list[EvaluationResult]


class EvaluationSummary(BaseModel):
    suite: Literal["ci", "full"]
    commit_sha: str
    faithfulness: float
    answer_relevance: float
    context_precision: float
    context_recall: float
    results: list[EvaluationResult]
