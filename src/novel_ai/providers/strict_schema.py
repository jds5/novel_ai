from __future__ import annotations

from copy import deepcopy
from typing import Any

STRICT_SCHEMA_NORMALIZER_VERSION = 1


def normalize_openai_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Add type declarations required by OpenAI without changing schema semantics."""

    normalized = deepcopy(schema)
    _normalize_node(normalized)
    return normalized


def _normalize_node(node: object) -> None:
    if isinstance(node, list):
        for item in node:
            _normalize_node(item)
        return
    if not isinstance(node, dict):
        return

    if "type" not in node:
        if "const" in node:
            inferred = _json_type(node["const"])
            if inferred is not None:
                node["type"] = inferred
        elif isinstance(node.get("enum"), list):
            inferred_types = {_json_type(value) for value in node["enum"]}
            if len(inferred_types) == 1 and None not in inferred_types:
                node["type"] = inferred_types.pop()

    for value in node.values():
        _normalize_node(value)


def _json_type(value: object) -> str | None:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return None
