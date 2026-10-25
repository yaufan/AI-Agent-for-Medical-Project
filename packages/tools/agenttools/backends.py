"""Build the model backend an evaluation or the UI asks for.

provider "openai": any OpenAI-compatible server (llama.cpp, vLLM, Ollama) at base_url.
provider "anthropic": Claude through the Anthropic SDK, always behind the gateway with no local
model, so a call whose content is above the cloud limit is refused instead of sent.
"""
from __future__ import annotations

import os

import httpx

from . import agent
from .core import Session

ERRORS: tuple[type[Exception], ...] = (httpx.HTTPError, KeyError, ValueError)
try:
    import anthropic

    ERRORS = ERRORS + (anthropic.APIError,)
except ImportError:  # the Anthropic SDK is optional
    anthropic = None


def make_llm(provider: str, model: str, base_url: str | None = None, timeout: float = 300.0, retries: int = 0,
             session: Session | None = None, extra_body: dict | None = None):
    if provider == "anthropic":
        from .claude_llm import ClaudeLLM
        from .gateway import RoutedLLM

        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise SystemExit("provider anthropic needs ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) in the environment")
        cloud = ClaudeLLM(model)
        return RoutedLLM(None, cloud, session) if session is not None else cloud
    return agent.ChatLLM(base_url, model, timeout=timeout, retries=retries, extra_body=extra_body)
