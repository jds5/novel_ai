import pytest
from jsonschema import ValidationError

from novel_ai.prompts.catalog import get_prompt_catalog
from novel_ai.prompts.loader import PromptCatalogError


def test_catalog_discovers_versioned_prompt_assets() -> None:
    definitions = get_prompt_catalog().list_definitions()

    assert {(item.manifest.key, item.manifest.version) for item in definitions} == {
        ("chapter_length_reviser", 1),
        ("chapter_length_reviser", 2),
        ("chapter_length_reviser", 3),
        ("chapter_style_reviser", 1),
        ("continuity_reviewer", 1),
        ("prose_purity_reviewer", 1),
        ("scene_planner", 1),
        ("scene_writer", 1),
        ("scene_writer", 2),
        ("scene_writer", 3),
        ("state_extractor", 1),
        ("work_planner", 1),
        ("work_planner", 2),
    }
    assert all(len(item.fingerprint) == 64 for item in definitions)


def test_renderer_requires_exact_manifest_variables() -> None:
    catalog = get_prompt_catalog()
    definition = catalog.get("scene_writer", 1)
    valid_variables = {name: {"value": name} for name in definition.manifest.required_variables}

    rendered = catalog.render("scene_writer", valid_variables, version=1)

    assert "{{" not in rendered.system
    assert "{{" not in rendered.user
    assert '"value": "scene_plan"' in rendered.user

    invalid_variables = dict(valid_variables)
    invalid_variables.pop("scene_plan")
    invalid_variables["unexpected"] = "value"
    with pytest.raises(PromptCatalogError, match="missing=.*scene_plan.*extra=.*unexpected"):
        catalog.render("scene_writer", invalid_variables, version=1)


def test_latest_work_planner_expands_a_one_line_premise() -> None:
    rendered = get_prompt_catalog().render(
        "work_planner",
        {
            "work_profile": {"title": "旧城"},
            "author_intent": "一个失去名字的铸剑师回到所有人都认识他的旧城。",
            "previous_directions": [],
            "generation_nonce": "candidate-1",
        },
    )

    assert rendered.version == 2
    assert "一句话创意" in rendered.system
    assert "失去名字的铸剑师" in rendered.user


def test_scene_writer_output_schema_rejects_extra_commentary() -> None:
    catalog = get_prompt_catalog()
    valid = {
        "schemaVersion": 1,
        "artifactType": "SCENE_PROSE",
        "sceneId": "scene-1",
        "prose": "雨落在旧城墙上。",
    }
    catalog.validate_output("scene_writer", valid)

    with pytest.raises(ValidationError):
        catalog.validate_output("scene_writer", {**valid, "analysis": "先分析一下"})
