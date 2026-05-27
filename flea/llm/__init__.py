from flea.config import Config
from flea.llm.base import LLMClient
from flea.llm.openai_client import OpenAIClient


def make_llm_client(cfg: Config) -> LLMClient:
    """Build the LLM client configured for the project."""
    if cfg.llm_provider == "openai":
        return OpenAIClient(
            api_key=cfg.openai_api_key or "",
            default_extraction_model=cfg.extraction_model,
            default_reasoning_model=cfg.fusion_model,
        )
    raise ValueError(f"Unknown LLM provider: {cfg.llm_provider}")


__all__ = ["LLMClient", "make_llm_client"]
