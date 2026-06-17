"""
LLM provider factory.

Returns the appropriate TableSummarizer class based on the chosen provider.
Both providers expose the same public API so the rest of the codebase stays
unchanged.

Supported values:
    - "ollama"  → src.llm.providers.ollama.summarizer.TableSummarizer
    - "gemini"  → src.llm.providers.gemini.summarizer.TableSummarizer
"""

import os
from dotenv import load_dotenv

load_dotenv()


def get_summarizer(provider: str | None = None, **kwargs):
    """
    Instantiate and return the correct TableSummarizer.

    Args:
        provider: "ollama" or "gemini". Falls back to the LLM_PROVIDER
                  env var, then to "ollama".
        **kwargs: Forwarded to the provider's constructor
                  (e.g. model_name="gemini-2.5-flash").
    """
    provider = (provider or os.getenv("LLM_PROVIDER", "ollama")).strip().lower()

    if provider == "gemini":
        from src.llm.providers.gemini.summarizer import TableSummarizer
    elif provider == "ollama":
        from src.llm.providers.ollama.summarizer import TableSummarizer
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider}'. "
            "Supported values: 'ollama', 'gemini'."
        )

    return TableSummarizer(**kwargs)
