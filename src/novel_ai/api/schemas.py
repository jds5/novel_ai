from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class WorkCreate(ApiModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)


class WorkSummary(ApiModel):
    id: UUID
    title: str
    description: str | None
    status: str
    chapter_count: int
    total_char_count: int
    version: int
    updated_at: datetime


class WorkUpdate(ApiModel):
    expected_version: int = Field(ge=1)
    description: str | None = Field(default=None, max_length=4000)
    core_pitch: str | None = Field(default=None, max_length=20_000)
    themes: str | None = Field(default=None, max_length=20_000)
    main_plot: str | None = Field(default=None, max_length=100_000)
    outline_markdown: str | None = Field(default=None, max_length=200_000)
    ending_constraints: str | None = Field(default=None, max_length=50_000)
    story_bible: str | None = Field(default=None, max_length=200_000)
    style_contract: str | None = Field(default=None, max_length=50_000)
    forbidden_content: str | None = Field(default=None, max_length=50_000)


class WorkDetail(WorkSummary):
    settings: dict[str, Any]
    commit_sequence: int


class WorkPlanningGenerationRequest(ApiModel):
    author_intent: str = Field(default="", max_length=20_000)
    prior_core_pitches: list[str] = Field(default_factory=list, max_length=5)
    prior_candidate_hashes: list[str] = Field(default_factory=list, max_length=10)


class WorkPlanningCandidate(ApiModel):
    schema_version: int
    artifact_type: str
    candidate_id: str
    description: str
    core_pitch: str
    themes: str
    main_plot: str
    outline_markdown: str
    ending_constraints: str
    story_bible: str
    style_contract: str
    forbidden_content: str
    content_hash: str


class ChapterCreate(ApiModel):
    chapter_number: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, max_length=300)
    generation_brief: str | None = Field(default=None, max_length=20_000)
    target_char_count: int = Field(default=2500, ge=100, le=200_000)


class ChapterUpdate(ApiModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=300)
    generation_brief: str | None = Field(default=None, max_length=20_000)
    target_char_count: int = Field(ge=100, le=200_000)


class ChapterContentUpdate(ApiModel):
    content: str
    expected_revision_number: int = Field(ge=0)


class ChapterSummary(ApiModel):
    id: UUID
    work_id: UUID
    chapter_number: int
    title: str | None
    status: str
    version: int
    latest_revision_id: UUID | None
    latest_revision_number: int
    latest_revision_source: str | None
    is_canonical: bool
    char_count: int
    updated_at: datetime


class ChapterDetail(ChapterSummary):
    summary: str | None
    generation_brief: str | None
    target_char_count: int
    content: str
    content_hash: str | None


class ChapterPage(ApiModel):
    items: list[ChapterSummary]
    next_after: int | None


class ChapterRevisionSummary(ApiModel):
    id: UUID
    revision_number: int
    parent_revision_id: UUID | None
    source: str
    char_count: int
    is_canonical: bool
    canonical_commit_sequence: int | None
    workflow_run_id: UUID | None
    created_at: datetime


class ChapterRevisionDetail(ChapterRevisionSummary):
    content: str
    content_hash: str


class ChapterRevisionPage(ApiModel):
    items: list[ChapterRevisionSummary]
    next_before: int | None


class GenerationHandleResponse(ApiModel):
    run_id: UUID
    status: str


class WorkflowStepResponse(ApiModel):
    key: str
    ordinal: int
    status: str
    attempt_count: int
    error: dict[str, Any] | None


class GenerationStatusResponse(ApiModel):
    run_id: UUID
    chapter_id: UUID | None
    status: str
    version: int
    steps: list[WorkflowStepResponse]
    provider: str | None
    model: str | None
    usage: dict[str, Any] | None
    error: dict[str, Any] | None
    candidate_revision_id: UUID | None
    lease_expires_at: datetime | None
    updated_at: datetime
