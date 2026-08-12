import pytest

from novel_ai.domain.prose_purity import (
    ProseContractError,
    PurityCategory,
    TransportStatus,
    parse_and_scan_scene_prose,
)


def test_clean_narrative_dialogue_does_not_trigger_keyword_filter() -> None:
    payload = {
        "schemaVersion": 1,
        "artifactType": "SCENE_PROSE",
        "sceneId": "scene-1",
        "prose": "沈砚压低声音：“让我分析一下。门外有三个人。”雨声吞掉了最后一个字。",
    }

    _, result = parse_and_scan_scene_prose(
        payload,
        expected_scene_id="scene-1",
        transport=TransportStatus(completed=True, finish_reason="stop"),
    )

    assert result.accepted


def test_preamble_reasoning_and_postscript_are_rejected() -> None:
    payload = {
        "schemaVersion": 1,
        "artifactType": "SCENE_PROSE",
        "sceneId": "scene-1",
        "prose": "以下是小说正文：\n思考过程：先制造冲突。\n门开了。\n如需调整请告诉我。",
    }

    _, result = parse_and_scan_scene_prose(
        payload,
        expected_scene_id="scene-1",
        transport=TransportStatus(completed=True, finish_reason="stop"),
    )

    assert not result.accepted
    assert {finding.category for finding in result.findings} >= {
        PurityCategory.PREAMBLE,
        PurityCategory.REASONING_LEAK,
        PurityCategory.POSTSCRIPT,
    }


def test_transport_truncation_is_rejected_even_if_text_looks_clean() -> None:
    _, result = parse_and_scan_scene_prose(
        {
            "schemaVersion": 1,
            "artifactType": "SCENE_PROSE",
            "sceneId": "scene-1",
            "prose": "门开了，他",
        },
        expected_scene_id="scene-1",
        transport=TransportStatus(completed=False, finish_reason="length"),
    )

    assert result.findings[0].category == PurityCategory.REFUSAL_OR_TRUNCATION


def test_scene_identity_is_part_of_the_contract() -> None:
    with pytest.raises(ProseContractError, match="scene id mismatch"):
        parse_and_scan_scene_prose(
            {
                "schemaVersion": 1,
                "artifactType": "SCENE_PROSE",
                "sceneId": "wrong-scene",
                "prose": "门开了。",
            },
            expected_scene_id="scene-1",
            transport=TransportStatus(completed=True),
        )
