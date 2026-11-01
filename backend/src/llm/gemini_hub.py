"""
Calls hosted Gemini models with automatic fallback.

Greywiz does not train or host a model; it calls models through Google's API.
Free-tier keys allow only a small number of requests per model per day, so a
request that hits a quota (429) or an overloaded model (503) is retried on the
next model in GEMINI_MODELS instead of failing the worker's report.
"""

from __future__ import annotations

import os

from google import genai
from google.genai import errors, types

DEFAULT_MODELS = "gemini-2.5-flash,gemini-3.5-flash,gemini-3-flash-preview,gemini-2.5-flash-lite,gemini-3.5-flash-lite"
RETRYABLE_STATUS = {429, 500, 503, 504}


class NoModelAvailableError(RuntimeError):
    """Every configured model refused the request (quota or outage)."""


def model_chain() -> list[str]:
    preferred = os.getenv("GEMINI_LLM_MODEL", "").strip()
    chain = [m.strip() for m in os.getenv("GEMINI_MODELS", DEFAULT_MODELS).split(",") if m.strip()]
    if preferred:
        chain = [preferred] + [m for m in chain if m != preferred]
    return chain


def client() -> genai.Client:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set in backend/.env.")
    # One attempt per model: on a quota or overload error we move to the next
    # model at once instead of letting the SDK back off and retry for minutes.
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1),
            timeout=int(os.getenv("GEMINI_TIMEOUT_MS", "90000")),
        ),
    )


def generate(contents, config: types.GenerateContentConfig | None = None, gemini: genai.Client | None = None):
    """generate_content on the first model in the chain that accepts the request.

    Returns (response, model_name).
    """
    gemini = gemini or client()
    failures = []
    for model in model_chain():
        try:
            response = gemini.models.generate_content(model=model, contents=contents, config=config)
            return response, model
        except errors.APIError as e:
            if e.code not in RETRYABLE_STATUS:
                raise
            failures.append(f"{model}: {e.code}")
            print(f"[gemini] {model} unavailable ({e.code}); trying the next model")
    raise NoModelAvailableError(
        "All Gemini models are out of quota or unavailable right now ("
        + ", ".join(failures)
        + "). Free-tier keys allow about 20 requests per model per day; "
        "enable billing on the key or try again later."
    )
