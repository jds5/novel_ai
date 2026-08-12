from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PromptManifest(BaseModel):
    """Machine-readable contract for one immutable prompt version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(ge=1)
    role: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required_variables: tuple[str, ...]
    output_mode: Literal["structured", "text"]
    schema_path: str | None = None

    @model_validator(mode="after")
    def schema_matches_output_mode(self) -> PromptManifest:
        if self.output_mode == "structured" and self.schema_path is None:
            raise ValueError("structured prompts require schema_path")
        if self.output_mode == "text" and self.schema_path is not None:
            raise ValueError("text prompts must not declare schema_path")
        if len(set(self.required_variables)) != len(self.required_variables):
            raise ValueError("required_variables contains duplicates")
        return self


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    manifest: PromptManifest
    system_template: str
    user_template: str
    output_schema: dict[str, Any] | None
    source: str

    @property
    def fingerprint(self) -> str:
        payload = {
            "manifest": self.manifest.model_dump(mode="json"),
            "system": self.system_template,
            "user": self.user_template,
            "schema": self.output_schema,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def public_metadata(self) -> dict[str, object]:
        return {
            "key": self.manifest.key,
            "version": self.manifest.version,
            "role": self.manifest.role,
            "description": self.manifest.description,
            "output_mode": self.manifest.output_mode,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    key: str
    version: int
    fingerprint: str
    system: str
    user: str
    output_schema: dict[str, Any] | None
