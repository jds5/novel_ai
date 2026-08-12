from novel_ai.db import models  # noqa: F401
from novel_ai.db.base import Base


def test_core_tables_are_registered() -> None:
    assert {
        "works",
        "chapters",
        "artifacts",
        "workflow_runs",
        "workflow_steps",
        "artifact_dependencies",
        "context_snapshots",
        "generation_runs",
        "chapter_revisions",
        "change_sets",
        "event_type_definitions",
        "story_events",
        "item_ownership_projection",
        "semantic_memories",
        "outbox_events",
    } <= set(Base.metadata.tables)


def test_chapter_content_is_indirect_and_revisioned() -> None:
    chapters = Base.metadata.tables["chapters"]
    revisions = Base.metadata.tables["chapter_revisions"]
    artifacts = Base.metadata.tables["artifacts"]

    assert "content_text" not in chapters.c
    assert "latest_revision_id" in chapters.c
    assert "prose_artifact_id" in revisions.c
    assert "char_count" in revisions.c
    assert "content_text" in artifacts.c
