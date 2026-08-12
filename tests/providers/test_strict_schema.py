from novel_ai.providers.strict_schema import normalize_openai_strict_schema


def test_strict_schema_normalizer_adds_only_semantically_equivalent_types() -> None:
    source = {
        "type": "object",
        "properties": {
            "version": {"const": 1},
            "kind": {"const": "SCENE_PROSE"},
            "decision": {"enum": ["PASS", "FAIL"]},
            "mixed": {"enum": [1, "one"]},
        },
    }

    normalized = normalize_openai_strict_schema(source)

    assert normalized["properties"]["version"] == {"const": 1, "type": "integer"}
    assert normalized["properties"]["kind"] == {
        "const": "SCENE_PROSE",
        "type": "string",
    }
    assert normalized["properties"]["decision"] == {
        "enum": ["PASS", "FAIL"],
        "type": "string",
    }
    assert normalized["properties"]["mixed"] == {"enum": [1, "one"]}
    assert "type" not in source["properties"]["version"]
