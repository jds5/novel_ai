from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ExecutorKind(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    MODEL = "MODEL"
    HUMAN_GATE = "HUMAN_GATE"
    TRANSACTION = "TRANSACTION"
    OUTBOX = "OUTBOX"


@dataclass(frozen=True, slots=True)
class StepDefinition:
    key: str
    executor: ExecutorKind
    output_artifact_kind: str | None
    prompt_key: str | None = None


CHAPTER_WORKFLOW_V1: tuple[StepDefinition, ...] = (
    StepDefinition("load_chapter_task", ExecutorKind.DETERMINISTIC, "CHAPTER_TASK_SNAPSHOT"),
    StepDefinition("compile_context", ExecutorKind.DETERMINISTIC, "CONTEXT_SNAPSHOT"),
    StepDefinition("plan_scenes", ExecutorKind.MODEL, "SCENE_PLAN", "scene_planner"),
    StepDefinition("validate_scene_plan", ExecutorKind.DETERMINISTIC, "VALIDATION_REPORT"),
    StepDefinition("write_scenes", ExecutorKind.MODEL, "SCENE_PROSE", "scene_writer"),
    StepDefinition("assemble_chapter", ExecutorKind.DETERMINISTIC, "CHAPTER_PROSE"),
    StepDefinition("revise_style", ExecutorKind.MODEL, "CHAPTER_PROSE", "chapter_style_reviser"),
    StepDefinition("scan_prose_purity", ExecutorKind.DETERMINISTIC, "VALIDATION_REPORT"),
    StepDefinition(
        "review_prose_purity",
        ExecutorKind.MODEL,
        "PROSE_PURITY_REVIEW",
        "prose_purity_reviewer",
    ),
    StepDefinition(
        "extract_change_set", ExecutorKind.MODEL, "CHANGE_SET_PROPOSAL", "state_extractor"
    ),
    StepDefinition(
        "review_continuity",
        ExecutorKind.MODEL,
        "CONTINUITY_REVIEW",
        "continuity_reviewer",
    ),
    StepDefinition("validate_change_set", ExecutorKind.DETERMINISTIC, "VALIDATION_REPORT"),
    StepDefinition("approve_change_set", ExecutorKind.HUMAN_GATE, None),
    StepDefinition("commit_chapter", ExecutorKind.TRANSACTION, "CANONICAL_COMMIT_RECEIPT"),
    StepDefinition("dispatch_post_commit", ExecutorKind.OUTBOX, None),
)


INTERACTIVE_DRAFT_WORKFLOW_V1: tuple[StepDefinition, ...] = (
    StepDefinition("load_chapter_task", ExecutorKind.DETERMINISTIC, "CHAPTER_TASK_SNAPSHOT"),
    StepDefinition("compile_context", ExecutorKind.DETERMINISTIC, "CONTEXT_SNAPSHOT"),
    StepDefinition("write_chapter", ExecutorKind.MODEL, "CHAPTER_PROSE", "scene_writer"),
    StepDefinition("scan_prose_purity", ExecutorKind.DETERMINISTIC, "VALIDATION_REPORT"),
    StepDefinition("save_candidate", ExecutorKind.TRANSACTION, "CHAPTER_REVISION"),
    StepDefinition("review_candidate", ExecutorKind.HUMAN_GATE, None),
)


WORK_PLANNING_ASSISTANT_V1: tuple[StepDefinition, ...] = (
    StepDefinition("capture_author_brief", ExecutorKind.DETERMINISTIC, "WORK_PLAN_REQUEST"),
    StepDefinition("compile_work_plan_context", ExecutorKind.DETERMINISTIC, "CONTEXT_SNAPSHOT"),
    StepDefinition(
        "generate_work_plan", ExecutorKind.MODEL, "WORK_PLANNING_CANDIDATE", "work_planner"
    ),
    StepDefinition("save_work_plan_candidate", ExecutorKind.TRANSACTION, "WORK_PLANNING_CANDIDATE"),
    StepDefinition("review_work_plan_candidate", ExecutorKind.HUMAN_GATE, None),
)


def validate_workflow_definition(steps: tuple[StepDefinition, ...]) -> None:
    keys = [step.key for step in steps]
    if len(keys) != len(set(keys)):
        raise ValueError("workflow step keys must be unique")
    for step in steps:
        if step.executor == ExecutorKind.MODEL and step.prompt_key is None:
            raise ValueError(f"model step {step.key!r} must declare prompt_key")
        if step.executor != ExecutorKind.MODEL and step.prompt_key is not None:
            raise ValueError(f"non-model step {step.key!r} cannot declare prompt_key")


validate_workflow_definition(CHAPTER_WORKFLOW_V1)
validate_workflow_definition(INTERACTIVE_DRAFT_WORKFLOW_V1)
validate_workflow_definition(WORK_PLANNING_ASSISTANT_V1)
