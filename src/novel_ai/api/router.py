from fastapi import APIRouter

from novel_ai import __version__
from novel_ai.api.writing import router as writing_router
from novel_ai.config import get_settings
from novel_ai.prompts.catalog import get_prompt_catalog
from novel_ai.providers.factory import provider_definitions

router = APIRouter()
router.include_router(writing_router)


@router.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/prompt-definitions", tags=["prompts"])
def list_prompt_definitions() -> list[dict[str, object]]:
    """Expose prompt metadata without leaking full prompt bodies."""

    catalog = get_prompt_catalog()
    return [definition.public_metadata() for definition in catalog.list_definitions()]


@router.get("/model-providers", tags=["models"])
def list_model_providers() -> list[dict[str, object]]:
    """Expose capabilities and configuration state without exposing credentials."""

    return [definition.public_metadata() for definition in provider_definitions(get_settings())]
