from __future__ import annotations

import json
import re
from collections.abc import Mapping
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

from novel_ai.prompts.models import PromptDefinition, PromptManifest, RenderedPrompt

_VARIABLE_PATTERN = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


class PromptCatalogError(ValueError):
    """Raised when prompt assets or rendering inputs violate their contract."""


class PromptCatalog:
    def __init__(self, definitions: Mapping[tuple[str, int], PromptDefinition]) -> None:
        self._definitions = dict(definitions)

    @classmethod
    def discover(cls, package: str = "novel_ai.prompts.catalog") -> PromptCatalog:
        root = files(package)
        definitions: dict[tuple[str, int], PromptDefinition] = {}
        for prompt_directory in sorted(root.iterdir(), key=lambda item: item.name):
            if not prompt_directory.is_dir() or prompt_directory.name.startswith("_"):
                continue
            for version_directory in sorted(prompt_directory.iterdir(), key=lambda item: item.name):
                if not version_directory.is_dir() or not version_directory.name.startswith("v"):
                    continue
                manifest = PromptManifest.model_validate_json(
                    version_directory.joinpath("manifest.json").read_text(encoding="utf-8")
                )
                expected_version_directory = f"v{manifest.version}"
                if prompt_directory.name != manifest.key:
                    raise PromptCatalogError(
                        f"prompt directory {prompt_directory.name!r} does not match key "
                        f"{manifest.key!r}"
                    )
                if version_directory.name != expected_version_directory:
                    raise PromptCatalogError(
                        f"version directory {version_directory.name!r} does not match "
                        f"version {manifest.version}"
                    )
                system_template = version_directory.joinpath("system.md").read_text(
                    encoding="utf-8"
                )
                user_template = version_directory.joinpath("user.md").read_text(encoding="utf-8")
                actual_variables = set(
                    _VARIABLE_PATTERN.findall(system_template + "\n" + user_template)
                )
                declared_variables = set(manifest.required_variables)
                if actual_variables != declared_variables:
                    raise PromptCatalogError(
                        f"variable contract mismatch for {manifest.key} v{manifest.version}: "
                        f"declared={sorted(declared_variables)}, actual={sorted(actual_variables)}"
                    )
                output_schema: dict[str, Any] | None = None
                if manifest.schema_path is not None:
                    schema_text = version_directory.joinpath(manifest.schema_path).read_text(
                        encoding="utf-8"
                    )
                    loaded_schema = json.loads(schema_text)
                    if not isinstance(loaded_schema, dict):
                        raise PromptCatalogError("output schema root must be an object")
                    Draft202012Validator.check_schema(loaded_schema)
                    output_schema = loaded_schema
                key = (manifest.key, manifest.version)
                if key in definitions:
                    raise PromptCatalogError(f"duplicate prompt definition: {key}")
                definitions[key] = PromptDefinition(
                    manifest=manifest,
                    system_template=system_template,
                    user_template=user_template,
                    output_schema=output_schema,
                    source=f"{package}/{prompt_directory.name}/{version_directory.name}",
                )
        if not definitions:
            raise PromptCatalogError(f"no prompt definitions found in {package}")
        return cls(definitions)

    def list_definitions(self) -> tuple[PromptDefinition, ...]:
        return tuple(
            self._definitions[key]
            for key in sorted(self._definitions, key=lambda item: (item[0], item[1]))
        )

    def get(self, key: str, version: int | None = None) -> PromptDefinition:
        if version is None:
            versions = [
                candidate_version
                for candidate_key, candidate_version in self._definitions
                if candidate_key == key
            ]
            if not versions:
                raise KeyError(f"unknown prompt key: {key}")
            version = max(versions)
        try:
            return self._definitions[(key, version)]
        except KeyError as exc:
            raise KeyError(f"unknown prompt version: {key} v{version}") from exc

    def render(
        self,
        key: str,
        variables: Mapping[str, object],
        *,
        version: int | None = None,
    ) -> RenderedPrompt:
        definition = self.get(key, version)
        required = set(definition.manifest.required_variables)
        provided = set(variables)
        missing = required - provided
        extra = provided - required
        if missing or extra:
            raise PromptCatalogError(
                f"invalid variables for {key} v{definition.manifest.version}: "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )
        rendered_values = {
            name: _serialize_template_value(value) for name, value in variables.items()
        }
        return RenderedPrompt(
            key=definition.manifest.key,
            version=definition.manifest.version,
            fingerprint=definition.fingerprint,
            system=_render_template(definition.system_template, rendered_values),
            user=_render_template(definition.user_template, rendered_values),
            output_schema=definition.output_schema,
        )

    def validate_output(self, key: str, output: object, *, version: int | None = None) -> None:
        definition = self.get(key, version)
        if definition.output_schema is None:
            return
        Draft202012Validator(definition.output_schema).validate(output)


def _serialize_template_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _render_template(template: str, values: Mapping[str, str]) -> str:
    return _VARIABLE_PATTERN.sub(lambda match: values[match.group(1)], template)
