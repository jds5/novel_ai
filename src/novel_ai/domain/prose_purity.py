from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from novel_ai.domain.artifacts import normalize_text


class PurityCategory(StrEnum):
    PREAMBLE = "PREAMBLE"
    POSTSCRIPT = "POSTSCRIPT"
    REASONING_LEAK = "REASONING_LEAK"
    SELF_EVALUATION = "SELF_EVALUATION"
    PROMPT_ECHO = "PROMPT_ECHO"
    NON_PROSE_WRAPPER = "NON_PROSE_WRAPPER"
    PLACEHOLDER = "PLACEHOLDER"
    REFUSAL_OR_TRUNCATION = "REFUSAL_OR_TRUNCATION"


@dataclass(frozen=True, slots=True)
class PurityFinding:
    category: PurityCategory
    start: int
    end: int
    evidence: str
    rule: str


@dataclass(frozen=True, slots=True)
class TransportStatus:
    completed: bool
    refused: bool = False
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PurityGateResult:
    accepted: bool
    findings: tuple[PurityFinding, ...]


class SceneProseEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schemaVersion: int = Field(default=1, frozen=True)
    artifactType: str = Field(default="SCENE_PROSE", frozen=True)
    sceneId: str = Field(min_length=1)
    prose: str = Field(min_length=1)


class ProseContractError(ValueError):
    pass


_POSITIONAL_RULES: tuple[tuple[PurityCategory, str, re.Pattern[str]], ...] = (
    (
        PurityCategory.PREAMBLE,
        "assistant-style preamble",
        re.compile(r"\A\s*(?:以下|下面|这里)(?:是|为).{0,24}(?:正文|场景|小说)[：:，,\s]"),
    ),
    (
        PurityCategory.NON_PROSE_WRAPPER,
        "markdown code fence",
        re.compile(r"```(?:json|markdown|text)?", re.IGNORECASE),
    ),
    (
        PurityCategory.NON_PROSE_WRAPPER,
        "markdown heading",
        re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S"),
    ),
    (
        PurityCategory.NON_PROSE_WRAPPER,
        "assistant role label",
        re.compile(r"(?mi)^\s*(?:assistant|作者|写作结果|正文内容)\s*[：:]"),
    ),
    (
        PurityCategory.PROMPT_ECHO,
        "prompt data delimiter",
        re.compile(r"</?(?:story-data|candidate-prose)(?:\s[^>]*)?>", re.IGNORECASE),
    ),
    (
        PurityCategory.PLACEHOLDER,
        "unresolved template variable",
        re.compile(r"{{\s*[A-Za-z_][A-Za-z0-9_]*\s*}}"),
    ),
    (
        PurityCategory.PLACEHOLDER,
        "draft placeholder",
        re.compile(r"(?:\[待补(?:充)?\]|【待补(?:充)?】|\bTODO\b)", re.IGNORECASE),
    ),
    (
        PurityCategory.REASONING_LEAK,
        "explicit reasoning section",
        re.compile(r"(?mi)^\s*(?:思考过程|推理过程|我的分析|分析如下)\s*[：:]"),
    ),
    (
        PurityCategory.SELF_EVALUATION,
        "explicit self-evaluation section",
        re.compile(r"(?m)^\s*(?:自我评价|完成度评价|写作点评|本次创作评价)\s*[：:]"),
    ),
    (
        PurityCategory.POSTSCRIPT,
        "assistant-style postscript",
        re.compile(
            r"(?m)\n\s*(?:以上(?:是|为).{0,20}(?:正文|场景)|写作说明|如需.{0,20}(?:调整|修改)).{0,80}\s*\Z"
        ),
    ),
)


def parse_scene_prose(payload: object, *, expected_scene_id: str) -> SceneProseEnvelope:
    try:
        envelope = SceneProseEnvelope.model_validate(payload)
    except ValidationError as exc:
        raise ProseContractError("scene prose does not match its output contract") from exc
    if envelope.schemaVersion != 1 or envelope.artifactType != "SCENE_PROSE":
        raise ProseContractError("unexpected scene prose schema or artifact type")
    if envelope.sceneId != expected_scene_id:
        raise ProseContractError(
            f"scene id mismatch: expected {expected_scene_id!r}, got {envelope.sceneId!r}"
        )
    return envelope.model_copy(update={"prose": normalize_text(envelope.prose)})


def scan_prose(
    prose: str,
    transport: TransportStatus,
    *,
    allow_markdown_headings: bool = False,
) -> PurityGateResult:
    """Run conservative deterministic checks before semantic purity review."""

    normalized = normalize_text(prose)
    findings: list[PurityFinding] = []
    if (
        not transport.completed
        or transport.refused
        or transport.finish_reason
        in {
            "length",
            "content_filter",
            "error",
        }
    ):
        findings.append(
            PurityFinding(
                category=PurityCategory.REFUSAL_OR_TRUNCATION,
                start=0,
                end=max(1, len(normalized)),
                evidence=normalized[:120],
                rule="provider response did not complete normally",
            )
        )
    if normalized.lstrip().startswith("{") and normalized.rstrip().endswith("}"):
        findings.append(
            PurityFinding(
                category=PurityCategory.NON_PROSE_WRAPPER,
                start=0,
                end=len(normalized),
                evidence=normalized[:120],
                rule="serialized JSON appears inside prose",
            )
        )
    for category, rule, pattern in _POSITIONAL_RULES:
        if allow_markdown_headings and rule == "markdown heading":
            continue
        for match in pattern.finditer(normalized):
            findings.append(
                PurityFinding(
                    category=category,
                    start=match.start(),
                    end=match.end(),
                    evidence=match.group(0)[:120],
                    rule=rule,
                )
            )
    ordered = tuple(sorted(findings, key=lambda item: (item.start, item.end, item.category)))
    return PurityGateResult(accepted=not ordered, findings=ordered)


def parse_and_scan_scene_prose(
    payload: dict[str, Any],
    *,
    expected_scene_id: str,
    transport: TransportStatus,
) -> tuple[SceneProseEnvelope, PurityGateResult]:
    envelope = parse_scene_prose(payload, expected_scene_id=expected_scene_id)
    return envelope, scan_prose(envelope.prose, transport)
