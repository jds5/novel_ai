from novel_ai.application.chapter_workflow import (
    CHAPTER_WORKFLOW_V1,
    INTERACTIVE_DRAFT_WORKFLOW_V1,
    WORK_PLANNING_ASSISTANT_V1,
    ExecutorKind,
)


def test_purity_gates_run_before_state_extraction_and_commit() -> None:
    positions = {step.key: index for index, step in enumerate(CHAPTER_WORKFLOW_V1)}

    assert positions["scan_prose_purity"] < positions["review_prose_purity"]
    assert positions["review_prose_purity"] < positions["extract_change_set"]
    assert positions["validate_change_set"] < positions["commit_chapter"]


def test_all_model_steps_reference_versioned_prompt_keys() -> None:
    model_steps = [step for step in CHAPTER_WORKFLOW_V1 if step.executor == ExecutorKind.MODEL]

    assert all(step.prompt_key for step in model_steps)


def test_interactive_draft_stops_at_human_review() -> None:
    assert INTERACTIVE_DRAFT_WORKFLOW_V1[-1].key == "review_candidate"
    assert INTERACTIVE_DRAFT_WORKFLOW_V1[-1].executor == ExecutorKind.HUMAN_GATE
    assert not any(step.key == "commit_chapter" for step in INTERACTIVE_DRAFT_WORKFLOW_V1)


def test_work_planner_produces_a_candidate_before_human_review() -> None:
    assert WORK_PLANNING_ASSISTANT_V1[-1].key == "review_work_plan_candidate"
    assert WORK_PLANNING_ASSISTANT_V1[-1].executor == ExecutorKind.HUMAN_GATE
    assert any(step.prompt_key == "work_planner" for step in WORK_PLANNING_ASSISTANT_V1)
