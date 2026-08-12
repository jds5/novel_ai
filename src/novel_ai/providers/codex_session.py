from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from novel_ai.providers.contracts import (
    ApiStyle,
    CompletionStatus,
    ModelRequest,
    ProviderCapabilities,
    ProviderName,
    ProviderResponse,
    StructuredOutputMode,
)
from novel_ai.providers.errors import (
    ProviderConfigurationError,
    ProviderResponseError,
    ProviderTransportError,
)
from novel_ai.providers.strict_schema import (
    STRICT_SCHEMA_NORMALIZER_VERSION,
    normalize_openai_strict_schema,
)

CODEX_SESSION_CAPABILITIES = ProviderCapabilities(
    provider=ProviderName.OPENAI_CODEX_SESSION,
    api_style=ApiStyle.CODEX_EXEC,
    structured_output_mode=StructuredOutputMode.STRICT_JSON_SCHEMA,
    separates_reasoning_from_final=True,
    exposes_finish_reason=False,
    supports_streaming=False,
    supports_output_token_limit=False,
    production_eligible=False,
    requires_local_user_session=True,
)

_LOCAL_ENVIRONMENTS = frozenset({"local", "development", "test"})
_ALLOWED_CODEX_ITEM_TYPES = frozenset({"reasoning", "agent_message"})
_PASSTHROUGH_ENVIRONMENT = frozenset(
    {
        "APPDATA",
        "CODEX_HOME",
        "COMSPEC",
        "HOME",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "NO_PROXY",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
)


@dataclass(frozen=True, slots=True)
class CodexCommandResult:
    returncode: int
    stdout: str
    stderr: str


class CodexCommandRunner(Protocol):
    async def __call__(
        self,
        command: tuple[str, ...],
        *,
        input_text: str | None,
        cwd: Path,
        timeout_seconds: float,
    ) -> CodexCommandResult: ...


class OpenAICodexSessionProvider:
    """Local, single-user test adapter backed by an official Codex ChatGPT login."""

    def __init__(
        self,
        *,
        enabled: bool,
        environment: str,
        executable: str = "codex",
        timeout_seconds: float = 600.0,
        auth_timeout_seconds: float = 10.0,
        runner: CodexCommandRunner | None = None,
    ) -> None:
        self._enabled = enabled
        self._environment = environment.strip().lower()
        self._executable = executable
        self._timeout_seconds = timeout_seconds
        self._auth_timeout_seconds = auth_timeout_seconds
        self._runner = runner or run_codex_command

    @property
    def capabilities(self) -> ProviderCapabilities:
        return CODEX_SESSION_CAPABILITIES

    async def generate(self, request: ModelRequest) -> ProviderResponse:
        self._validate_request(request)
        await self._require_chatgpt_login()

        started = time.perf_counter()
        invocation_id = f"codex-exec-{uuid4()}"
        transport_prompt = compile_codex_session_prompt(request)
        effective_output_schema = (
            normalize_openai_strict_schema(request.output_schema)
            if request.output_schema is not None
            else None
        )
        with tempfile.TemporaryDirectory(prefix="novel-ai-codex-") as temporary_directory:
            working_directory = Path(temporary_directory)
            output_path = working_directory / "final-message.txt"
            command = self._build_exec_command(request, working_directory, output_path)
            try:
                result = await self._runner(
                    command,
                    input_text=transport_prompt,
                    cwd=working_directory,
                    timeout_seconds=self._timeout_seconds,
                )
            except TimeoutError as exc:
                raise ProviderTransportError(
                    "Codex session generation timed out",
                    provider=ProviderName.OPENAI_CODEX_SESSION,
                    code="TIMEOUT",
                    retryable=True,
                ) from exc
            except OSError as exc:
                raise ProviderConfigurationError(
                    "Codex CLI could not be started",
                    provider=ProviderName.OPENAI_CODEX_SESSION,
                    code="CODEX_CLI_NOT_FOUND",
                    retryable=False,
                ) from exc

            if result.returncode != 0:
                self._raise_exec_failure(result)
            event_metadata = _parse_codex_events(result.stdout)
            try:
                final_text = output_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise ProviderResponseError(
                    "Codex CLI did not write its final message",
                    provider=ProviderName.OPENAI_CODEX_SESSION,
                    code="MISSING_FINAL_MESSAGE",
                    retryable=True,
                ) from exc

        if not final_text.strip():
            raise ProviderResponseError(
                "Codex CLI returned an empty final message",
                provider=ProviderName.OPENAI_CODEX_SESSION,
                code="EMPTY_FINAL_MESSAGE",
                retryable=True,
            )

        latency_ms = round((time.perf_counter() - started) * 1000)
        return ProviderResponse(
            provider=ProviderName.OPENAI_CODEX_SESSION,
            endpoint="codex://local/exec",
            response_id=invocation_id,
            model=request.model,
            status=CompletionStatus.COMPLETED,
            finish_reason="completed",
            final_text=final_text,
            refusal=None,
            output_item_types=event_metadata.item_types,
            usage=event_metadata.usage,
            raw_payload={
                "transport": "codex_exec",
                "transport_prompt": transport_prompt,
                "events_jsonl": result.stdout,
                "final_message": final_text,
                "thread_id": event_metadata.thread_id,
                "effective_output_schema": effective_output_schema,
                "schema_normalizer_version": STRICT_SCHEMA_NORMALIZER_VERSION,
            },
            latency_ms=latency_ms,
            request_id=invocation_id,
        )

    def _validate_request(self, request: ModelRequest) -> None:
        if not self._enabled:
            raise ProviderConfigurationError(
                "Codex session provider is disabled",
                provider=ProviderName.OPENAI_CODEX_SESSION,
                code="CODEX_SESSION_DISABLED",
                retryable=False,
            )
        if self._environment not in _LOCAL_ENVIRONMENTS:
            raise ProviderConfigurationError(
                "Codex session provider is restricted to local development and tests",
                provider=ProviderName.OPENAI_CODEX_SESSION,
                code="CODEX_SESSION_LOCAL_ONLY",
                retryable=False,
            )
        if request.temperature is not None:
            raise ProviderConfigurationError(
                "Codex session provider does not support temperature",
                provider=ProviderName.OPENAI_CODEX_SESSION,
                code="UNSUPPORTED_TEMPERATURE",
                retryable=False,
            )
        if request.thinking_enabled is not None:
            raise ProviderConfigurationError(
                "Codex session provider does not support thinking_enabled",
                provider=ProviderName.OPENAI_CODEX_SESSION,
                code="UNSUPPORTED_THINKING_PARAMETER",
                retryable=False,
            )

    async def _require_chatgpt_login(self) -> None:
        command = (self._executable, "login", "status")
        try:
            result = await self._runner(
                command,
                input_text=None,
                cwd=Path.cwd(),
                timeout_seconds=self._auth_timeout_seconds,
            )
        except TimeoutError as exc:
            raise ProviderConfigurationError(
                "Timed out while checking Codex login status",
                provider=ProviderName.OPENAI_CODEX_SESSION,
                code="CODEX_AUTH_CHECK_TIMEOUT",
                retryable=False,
            ) from exc
        except OSError as exc:
            raise ProviderConfigurationError(
                "Codex CLI could not be started",
                provider=ProviderName.OPENAI_CODEX_SESSION,
                code="CODEX_CLI_NOT_FOUND",
                retryable=False,
            ) from exc

        status_text = f"{result.stdout}\n{result.stderr}".lower()
        if result.returncode != 0 or "logged in using chatgpt" not in status_text:
            raise ProviderConfigurationError(
                "Codex CLI must be logged in using ChatGPT, not an API key",
                provider=ProviderName.OPENAI_CODEX_SESSION,
                code="CHATGPT_LOGIN_REQUIRED",
                retryable=False,
            )

    def _build_exec_command(
        self, request: ModelRequest, working_directory: Path, output_path: Path
    ) -> tuple[str, ...]:
        command = [self._executable]
        if request.reasoning_effort is not None:
            effort = json.dumps(request.reasoning_effort)
            command.extend(("--config", f"model_reasoning_effort={effort}"))
        command.extend(
            (
                "--ask-for-approval",
                "never",
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--color",
                "never",
                "--json",
                "--cd",
                str(working_directory),
                "--model",
                request.model,
                "--output-last-message",
                str(output_path),
            )
        )
        if request.output_schema is not None:
            schema_path = working_directory / "output-schema.json"
            schema_path.write_text(
                json.dumps(
                    normalize_openai_strict_schema(request.output_schema), ensure_ascii=False
                ),
                encoding="utf-8",
            )
            command.extend(("--output-schema", str(schema_path)))
        command.append("-")
        return tuple(command)

    @staticmethod
    def _raise_exec_failure(result: CodexCommandResult) -> None:
        diagnostic = f"{result.stdout}\n{result.stderr}".lower()
        if "usage limit" in diagnostic or "rate limit" in diagnostic or "quota" in diagnostic:
            raise ProviderTransportError(
                "Codex session usage limit was reached",
                provider=ProviderName.OPENAI_CODEX_SESSION,
                code="RATE_LIMITED",
                retryable=True,
            )
        if "not logged in" in diagnostic or "authentication" in diagnostic:
            raise ProviderConfigurationError(
                "Codex ChatGPT login is no longer valid",
                provider=ProviderName.OPENAI_CODEX_SESSION,
                code="CHATGPT_LOGIN_REQUIRED",
                retryable=False,
            )
        if "model" in diagnostic and ("not found" in diagnostic or "unsupported" in diagnostic):
            raise ProviderConfigurationError(
                "The requested model is not available to this Codex session",
                provider=ProviderName.OPENAI_CODEX_SESSION,
                code="MODEL_NOT_AVAILABLE",
                retryable=False,
            )
        raise ProviderTransportError(
            "Codex session process failed",
            provider=ProviderName.OPENAI_CODEX_SESSION,
            code="CODEX_EXEC_FAILED",
            retryable=False,
        )


def compile_codex_session_prompt(request: ModelRequest) -> str:
    """Serialize both roles without adding provider-specific behavioral instructions."""

    return json.dumps(
        {"system_instructions": request.system, "user_request": request.user},
        ensure_ascii=False,
        separators=(",", ":"),
    )


@dataclass(frozen=True, slots=True)
class _CodexEventMetadata:
    thread_id: str | None
    item_types: tuple[str, ...]
    usage: dict[str, Any]


def _parse_codex_events(raw_events: str) -> _CodexEventMetadata:
    thread_id: str | None = None
    item_types: list[str] = []
    usage: dict[str, Any] = {}
    event_count = 0
    for line in raw_events.splitlines():
        if not line.strip():
            continue
        event_count += 1
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                "Codex CLI emitted invalid JSONL events",
                provider=ProviderName.OPENAI_CODEX_SESSION,
                code="INVALID_EVENT_STREAM",
                retryable=True,
            ) from exc
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ProviderResponseError(
                "Codex CLI emitted an invalid event",
                provider=ProviderName.OPENAI_CODEX_SESSION,
                code="INVALID_EVENT_STREAM",
                retryable=True,
            )
        event_type = event["type"]
        if event_type == "thread.started" and isinstance(event.get("thread_id"), str):
            thread_id = event["thread_id"]
        if event_type in {"error", "turn.failed"}:
            raise ProviderResponseError(
                "Codex CLI reported a failed generation event",
                provider=ProviderName.OPENAI_CODEX_SESSION,
                code="FAILED_EVENT_STREAM",
                retryable=True,
            )
        if event_type == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
        if event_type in {"item.started", "item.completed"}:
            item = event.get("item")
            item_type = item.get("type") if isinstance(item, dict) else None
            if not isinstance(item_type, str):
                raise ProviderResponseError(
                    "Codex CLI emitted an item without a type",
                    provider=ProviderName.OPENAI_CODEX_SESSION,
                    code="INVALID_EVENT_STREAM",
                    retryable=True,
                )
            if item_type not in _ALLOWED_CODEX_ITEM_TYPES:
                raise ProviderResponseError(
                    f"Codex session attempted an unexpected item type: {item_type}",
                    provider=ProviderName.OPENAI_CODEX_SESSION,
                    code="UNEXPECTED_CODEX_ITEM",
                    retryable=False,
                )
            if event_type == "item.completed":
                item_types.append(item_type)
    if event_count == 0:
        raise ProviderResponseError(
            "Codex CLI emitted no JSONL events",
            provider=ProviderName.OPENAI_CODEX_SESSION,
            code="EMPTY_EVENT_STREAM",
            retryable=True,
        )
    return _CodexEventMetadata(
        thread_id=thread_id,
        item_types=tuple(item_types or ["agent_message"]),
        usage=usage,
    )


async def run_codex_command(
    command: tuple[str, ...],
    *,
    input_text: str | None,
    cwd: Path,
    timeout_seconds: float,
) -> CodexCommandResult:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE if input_text is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=_codex_subprocess_environment(os.environ),
        creationflags=creationflags,
    )
    encoded_input = input_text.encode("utf-8") if input_text is not None else None
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(encoded_input), timeout=timeout_seconds
        )
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise
    return CodexCommandResult(
        returncode=process.returncode or 0,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


def _codex_subprocess_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Pass only OS/auth-location variables; API keys cannot leak into the Codex child."""

    return {key: value for key, value in source.items() if key.upper() in _PASSTHROUGH_ENVIRONMENT}
