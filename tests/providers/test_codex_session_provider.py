import asyncio
import json
from pathlib import Path

import pytest

from novel_ai.providers.codex_session import (
    CodexCommandResult,
    OpenAICodexSessionProvider,
    _codex_subprocess_environment,
)
from novel_ai.providers.contracts import CompletionStatus, ModelRequest
from novel_ai.providers.errors import ProviderConfigurationError, ProviderResponseError


class FakeCodexRunner:
    def __init__(self, *, events: list[dict[str, object]], final_text: str) -> None:
        self.events = events
        self.final_text = final_text
        self.calls: list[tuple[tuple[str, ...], str | None, Path]] = []
        self.output_schemas: list[dict[str, object]] = []

    async def __call__(
        self,
        command: tuple[str, ...],
        *,
        input_text: str | None,
        cwd: Path,
        timeout_seconds: float,
    ) -> CodexCommandResult:
        del timeout_seconds
        self.calls.append((command, input_text, cwd))
        if command[-2:] == ("login", "status"):
            return CodexCommandResult(0, "Logged in using ChatGPT\n", "")
        if "--output-schema" in command:
            schema_index = command.index("--output-schema") + 1
            self.output_schemas.append(
                json.loads(Path(command[schema_index]).read_text(encoding="utf-8"))
            )
        output_index = command.index("--output-last-message") + 1
        Path(command[output_index]).write_text(self.final_text, encoding="utf-8")
        stdout = "\n".join(json.dumps(event) for event in self.events)
        return CodexCommandResult(0, stdout, "")


def request(**changes: object) -> ModelRequest:
    values: dict[str, object] = {
        "model": "gpt-test",
        "system": "只返回符合 Schema 的结果。",
        "user": "生成一个雨夜场景。",
        "max_output_tokens": 1000,
        "output_schema": {
            "type": "object",
            "required": ["prose"],
            "properties": {"prose": {"type": "string"}},
            "additionalProperties": False,
        },
        "schema_name": "scene_prose_v1",
        "reasoning_effort": "low",
    }
    values.update(changes)
    return ModelRequest(**values)  # type: ignore[arg-type]


def successful_events() -> list[dict[str, object]]:
    return [
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"id": "item-1", "type": "reasoning", "text": "不可进入正文"},
        },
        {
            "type": "item.completed",
            "item": {
                "id": "item-2",
                "type": "agent_message",
                "text": '{"prose":"雨落下来。"}',
            },
        },
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 8}},
    ]


def test_codex_session_uses_chatgpt_login_and_isolates_final_message() -> None:
    runner = FakeCodexRunner(events=successful_events(), final_text='{"prose":"雨落下来。"}')
    provider = OpenAICodexSessionProvider(
        enabled=True,
        environment="local",
        executable="codex-test",
        runner=runner,
    )

    response = asyncio.run(provider.generate(request()))

    assert response.status == CompletionStatus.COMPLETED
    assert response.final_text == '{"prose":"雨落下来。"}'
    assert "不可进入正文" not in response.final_text
    assert response.output_item_types == ("reasoning", "agent_message")
    assert response.usage == {"input_tokens": 10, "output_tokens": 8}

    assert runner.calls[0][0] == ("codex-test", "login", "status")
    command, input_text, working_directory = runner.calls[1]
    assert command[:5] == (
        "codex-test",
        "--config",
        'model_reasoning_effort="low"',
        "--ask-for-approval",
        "never",
    )
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--model") + 1] == "gpt-test"
    assert "--output-schema" in command
    assert runner.output_schemas[0]["properties"]["prose"] == {"type": "string"}
    assert command[-1] == "-"
    assert input_text is not None
    assert json.loads(input_text) == {
        "system_instructions": "只返回符合 Schema 的结果。",
        "user_request": "生成一个雨夜场景。",
    }
    assert working_directory != Path.cwd()


def test_codex_session_rejects_api_key_login() -> None:
    class ApiKeyRunner:
        async def __call__(
            self,
            command: tuple[str, ...],
            *,
            input_text: str | None,
            cwd: Path,
            timeout_seconds: float,
        ) -> CodexCommandResult:
            del command, input_text, cwd, timeout_seconds
            return CodexCommandResult(0, "Logged in using an API key\n", "")

    provider = OpenAICodexSessionProvider(enabled=True, environment="test", runner=ApiKeyRunner())

    with pytest.raises(ProviderConfigurationError) as raised:
        asyncio.run(provider.generate(request()))
    assert raised.value.code == "CHATGPT_LOGIN_REQUIRED"


def test_codex_session_rejects_tool_items() -> None:
    events = successful_events()
    events.insert(
        2,
        {
            "type": "item.started",
            "item": {"id": "tool-1", "type": "command_execution", "command": "dir"},
        },
    )
    provider = OpenAICodexSessionProvider(
        enabled=True,
        environment="local",
        runner=FakeCodexRunner(events=events, final_text='{"prose":"不应接收"}'),
    )

    with pytest.raises(ProviderResponseError) as raised:
        asyncio.run(provider.generate(request()))
    assert raised.value.code == "UNEXPECTED_CODEX_ITEM"


def test_codex_session_is_local_only_and_rejects_unmapped_parameters() -> None:
    runner = FakeCodexRunner(events=successful_events(), final_text="unused")
    production_provider = OpenAICodexSessionProvider(
        enabled=True, environment="production", runner=runner
    )
    with pytest.raises(ProviderConfigurationError) as production_error:
        asyncio.run(production_provider.generate(request()))
    assert production_error.value.code == "CODEX_SESSION_LOCAL_ONLY"
    assert not runner.calls

    local_provider = OpenAICodexSessionProvider(enabled=True, environment="local", runner=runner)
    with pytest.raises(ProviderConfigurationError) as parameter_error:
        asyncio.run(local_provider.generate(request(temperature=0.5)))
    assert parameter_error.value.code == "UNSUPPORTED_TEMPERATURE"
    assert not runner.calls


def test_codex_subprocess_environment_never_inherits_api_credentials() -> None:
    environment = _codex_subprocess_environment(
        {
            "PATH": "bin",
            "CODEX_HOME": "codex-home",
            "OPENAI_API_KEY": "must-not-leak",
            "DEEPSEEK_API_KEY": "must-not-leak",
            "DATABASE_URL": "must-not-leak",
        }
    )

    assert environment == {"PATH": "bin", "CODEX_HOME": "codex-home"}
