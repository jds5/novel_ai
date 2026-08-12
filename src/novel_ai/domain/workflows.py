from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from novel_ai.domain.artifacts import JSONValue, canonical_json


class WorkflowStatus(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StepStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"


_WORKFLOW_TRANSITIONS: dict[WorkflowStatus, frozenset[WorkflowStatus]] = {
    WorkflowStatus.PLANNED: frozenset({WorkflowStatus.RUNNING, WorkflowStatus.CANCELLED}),
    WorkflowStatus.RUNNING: frozenset(
        {
            WorkflowStatus.AWAITING_REVIEW,
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
    ),
    WorkflowStatus.AWAITING_REVIEW: frozenset(
        {WorkflowStatus.RUNNING, WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED}
    ),
    WorkflowStatus.FAILED: frozenset({WorkflowStatus.RUNNING, WorkflowStatus.CANCELLED}),
    WorkflowStatus.COMPLETED: frozenset(),
    WorkflowStatus.CANCELLED: frozenset(),
}

_STEP_TRANSITIONS: dict[StepStatus, frozenset[StepStatus]] = {
    StepStatus.PENDING: frozenset({StepStatus.RUNNING, StepStatus.CANCELLED}),
    StepStatus.RUNNING: frozenset({StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.CANCELLED}),
    StepStatus.SUCCEEDED: frozenset({StepStatus.STALE}),
    StepStatus.FAILED: frozenset({StepStatus.RUNNING, StepStatus.CANCELLED}),
    StepStatus.STALE: frozenset({StepStatus.RUNNING, StepStatus.CANCELLED}),
    StepStatus.CANCELLED: frozenset(),
}


class InvalidTransitionError(ValueError):
    pass


def transition_workflow(current: WorkflowStatus, target: WorkflowStatus) -> WorkflowStatus:
    if target not in _WORKFLOW_TRANSITIONS[current]:
        raise InvalidTransitionError(f"workflow cannot transition from {current} to {target}")
    return target


def transition_step(current: StepStatus, target: StepStatus) -> StepStatus:
    if target not in _STEP_TRANSITIONS[current]:
        raise InvalidTransitionError(f"step cannot transition from {current} to {target}")
    return target


def input_fingerprint(
    inputs: Mapping[str, str],
    *,
    configuration: Mapping[str, JSONValue] | None = None,
) -> str:
    """Fingerprint every exact dependency that makes a step result reusable."""

    payload: JSONValue = {
        "inputs": dict(sorted(inputs.items())),
        "configuration": dict(configuration or {}),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ArtifactDependency:
    input_hash: str
    output_hash: str


def find_invalidated_outputs(
    dependencies: Iterable[ArtifactDependency], changed_hashes: Iterable[str]
) -> frozenset[str]:
    """Return all direct and transitive outputs made stale by changed inputs."""

    downstream: dict[str, set[str]] = defaultdict(set)
    for dependency in dependencies:
        downstream[dependency.input_hash].add(dependency.output_hash)

    queue = deque(changed_hashes)
    visited_inputs: set[str] = set()
    invalidated: set[str] = set()
    while queue:
        input_hash = queue.popleft()
        if input_hash in visited_inputs:
            continue
        visited_inputs.add(input_hash)
        for output_hash in downstream[input_hash]:
            if output_hash not in invalidated:
                invalidated.add(output_hash)
                queue.append(output_hash)
    return frozenset(invalidated)
