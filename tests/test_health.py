import asyncio

from httpx import ASGITransport, AsyncClient, Response

from novel_ai.main import app


async def get(path: str) -> Response:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.get(path)


def test_health() -> None:
    response = asyncio.run(get("/api/v1/health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_root_redirects_to_packaged_writing_workspace() -> None:
    response = asyncio.run(get("/"))
    assert response.status_code == 307
    assert response.headers["location"] == "/app/"

    page = asyncio.run(get("/app/"))
    assert page.status_code == 200
    assert "长篇写作工作台" in page.text
    assert "一句话生成" in page.text
    assert 'id="planning-mode-manual"' in page.text
    assert 'id="planning-mode-ai"' in page.text

    stylesheet = asyncio.run(get("/app/styles.css"))
    assert stylesheet.status_code == 200
    assert "[hidden] { display: none !important; }" in stylesheet.text


def test_writing_workspace_routes_are_registered() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/works" in paths
    assert "/api/v1/works/{work_id}/planning-generation-runs" in paths
    assert "/api/v1/workflow-runs/{run_id}/planning-candidate" in paths
    assert "/api/v1/chapters/{chapter_id}/content" in paths
    assert "/api/v1/chapters/{chapter_id}/revisions" in paths
    assert "/api/v1/chapters/{chapter_id}/generation-runs" in paths
    assert "/api/v1/chapters/{chapter_id}/generation-runs/latest" in paths
    assert "/api/v1/workflow-runs/{run_id}" in paths


def test_prompt_definitions_hide_bodies() -> None:
    response = asyncio.run(get("/api/v1/prompt-definitions"))

    assert response.status_code == 200
    assert len(response.json()) == 13
    assert all("system" not in definition for definition in response.json())


def test_model_provider_metadata_does_not_expose_secrets() -> None:
    response = asyncio.run(get("/api/v1/model-providers"))

    assert response.status_code == 200
    definitions = response.json()
    assert {definition["provider"] for definition in definitions} == {
        "openai",
        "openai_codex_session",
        "deepseek",
    }
    assert next(item for item in definitions if item["provider"] == "openai")["aliases"] == [
        "chatgpt"
    ]
    session = next(item for item in definitions if item["provider"] == "openai_codex_session")
    assert session["aliases"] == ["codex_session"]
    assert session["production_eligible"] is False
    assert session["requires_local_user_session"] is True
    assert sum(definition["is_default"] is True for definition in definitions) == 1
    assert "api_key" not in response.text
