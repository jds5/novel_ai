from uuid import uuid4

import pytest

from novel_ai.domain.artifacts import Artifact, ArtifactKind, content_hash, normalize_text


def test_text_artifact_normalizes_before_hashing() -> None:
    work_id = uuid4()
    composed = "剑\r\n已出鞘"
    decomposed = "剑\n已出鞘"

    artifact = Artifact(
        work_id=work_id,
        kind=ArtifactKind.SCENE_PROSE,
        schema_version=1,
        text=composed,
    )

    assert artifact.text == normalize_text(decomposed)
    assert artifact.hash == content_hash(text=decomposed)


def test_json_hash_is_independent_of_object_key_order() -> None:
    assert content_hash(data={"b": 2, "a": 1}) == content_hash(data={"a": 1, "b": 2})


def test_artifact_requires_exactly_one_content_representation() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        Artifact(
            work_id=uuid4(),
            kind=ArtifactKind.SCENE_PLAN,
            schema_version=1,
        )
