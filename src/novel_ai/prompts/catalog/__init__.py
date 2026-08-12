from functools import lru_cache

from novel_ai.config import get_settings
from novel_ai.prompts.loader import PromptCatalog


@lru_cache(maxsize=1)
def get_prompt_catalog() -> PromptCatalog:
    return PromptCatalog.discover(get_settings().prompt_catalog_package)


__all__ = ["get_prompt_catalog"]
