import pytest

from novel_ai.domain.workflows import (
    ArtifactDependency,
    InvalidTransitionError,
    StepStatus,
    WorkflowStatus,
    find_invalidated_outputs,
    input_fingerprint,
    transition_step,
    transition_workflow,
)


def test_workflow_transitions_are_explicit() -> None:
    assert transition_workflow(WorkflowStatus.PLANNED, WorkflowStatus.RUNNING) == "RUNNING"
    assert transition_step(StepStatus.SUCCEEDED, StepStatus.STALE) == "STALE"

    with pytest.raises(InvalidTransitionError):
        transition_workflow(WorkflowStatus.COMPLETED, WorkflowStatus.RUNNING)


def test_input_fingerprint_is_stable_for_mapping_order() -> None:
    first = input_fingerprint(
        {"plan": "hash-a", "state": "hash-b"}, configuration={"temperature": 0.4}
    )
    second = input_fingerprint(
        {"state": "hash-b", "plan": "hash-a"}, configuration={"temperature": 0.4}
    )

    assert first == second
    assert first != input_fingerprint(
        {"state": "hash-b", "plan": "hash-c"}, configuration={"temperature": 0.4}
    )


def test_artifact_invalidation_is_transitive_but_scoped() -> None:
    dependencies = [
        ArtifactDependency("prose-v1", "facts-v1"),
        ArtifactDependency("facts-v1", "review-v1"),
        ArtifactDependency("other", "unrelated"),
    ]

    assert find_invalidated_outputs(dependencies, ["prose-v1"]) == {
        "facts-v1",
        "review-v1",
    }
