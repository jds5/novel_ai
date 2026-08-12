from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

type JSONValue = None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]


class ArtifactKind(StrEnum):
    CONTEXT_SNAPSHOT = "CONTEXT_SNAPSHOT"
    SCENE_PLAN = "SCENE_PLAN"
    SCENE_PROSE = "SCENE_PROSE"
    CHAPTER_PROSE = "CHAPTER_PROSE"
    PROSE_PURITY_REVIEW = "PROSE_PURITY_REVIEW"
    CHANGE_SET_PROPOSAL = "CHANGE_SET_PROPOSAL"
    CONTINUITY_REVIEW = "CONTINUITY_REVIEW"
    VALIDATION_REPORT = "VALIDATION_REPORT"
    SUMMARY = "SUMMARY"


def normalize_text(value: str) -> str:
    """Apply the sole canonical normalization used for prose hashing."""

    normalized_newlines = value.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", normalized_newlines)


def canonical_json(value: JSONValue) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(*, text: str | None = None, data: JSONValue | None = None) -> str:
    if (text is None) == (data is None):
        raise ValueError("exactly one of text or data is required")
    content = normalize_text(text) if text is not None else canonical_json(data)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Artifact:
    """Immutable model or workflow output prior to database persistence."""

    work_id: UUID
    kind: ArtifactKind
    schema_version: int
    text: str | None = None
    data: JSONValue | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        if (self.text is None) == (self.data is None):
            raise ValueError("an artifact must contain exactly one of text or data")
        if self.text is not None:
            object.__setattr__(self, "text", normalize_text(self.text))

    @property
    def hash(self) -> str:
        return (
            content_hash(text=self.text) if self.text is not None else content_hash(data=self.data)
        )
