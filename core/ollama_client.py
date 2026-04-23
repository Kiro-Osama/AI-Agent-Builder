"""
Local Ollama LLM client (OpenAI-compatible API).
===============================================
Uses POST {OLLAMA_BASE_URL}/v1/chat/completions (same shape as OpenRouter/OpenAI).

Select Ollama either:
- Per model id: prefix with `ollama:` e.g. `ollama:qwen3.5:4b-q4_K_M`
- Globally: `LLM_PROVIDER=ollama` + `OLLAMA_MODEL` (defaults to qwen3.5:4b-q4_K_M)
- Per HTTP/API request: `use_llm_provider("ollama"|"ollama_remote"|"openrouter")` (dashboard + chat)
- **Remote Ollama** (ngrok / other host): `LLM_PROVIDER=ollama_remote` or UI provider `ollama_remote`, plus:
  `OLLAMA_REMOTE_BASE_URL=https://your-tunnel.ngrok-free.app` (no `/v1` suffix),
  `OLLAMA_REMOTE_API_KEY=ollama` (dummy Bearer token, same as LangChain ChatOpenAI),
  optional `OLLAMA_REMOTE_MODEL`, `OLLAMA_REMOTE_NGROK_SKIP=1` for ngrok-free interstitial.

Same wire format as LangChain `ChatOpenAI(base_url=.../v1, api_key="ollama")` — we call httpx directly (no langchain dependency).

From Docker on Windows/Mac, set OLLAMA_BASE_URL=http://host.docker.internal:11434
"""
from __future__ import annotations

import contextvars
import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

import httpx

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_MODEL = "qwen3.5:4b-q4_K_M"

_llm_provider_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llm_provider_override",
    default=None,
)


def get_llm_provider_override() -> str | None:
    """Per-task UI selection: openrouter | ollama | ollama_remote | None."""
    return _llm_provider_override.get()


@contextmanager
def use_llm_provider(provider: str | None) -> Iterator[None]:
    """
    Scope LLM routing for this request/build (OpenRouter vs Ollama).
    `provider` should be 'openrouter', 'ollama', 'ollama_remote', or None/empty.
    """
    norm: str | None = None
    if provider is not None and str(provider).strip():
        p = str(provider).strip().lower()
        if p in ("openrouter", "ollama", "ollama_remote", "gemini"):
            norm = p
    token = _llm_provider_override.set(norm)
    try:
        yield
    finally:
        _llm_provider_override.reset(token)


def ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")


def default_ollama_model_tag() -> str:
    return os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL


def default_remote_model_tag() -> str:
    """Model name on the remote Ollama (OpenAI-compatible) server."""
    return (
        os.getenv("OLLAMA_REMOTE_MODEL", "").strip()
        or os.getenv("OLLAMA_MODEL", "").strip()
        or DEFAULT_OLLAMA_MODEL
    )


def _use_remote_ollama_http() -> bool:
    """True → POST to OLLAMA_REMOTE_BASE_URL (tunnel / second server)."""
    ovr = get_llm_provider_override()
    if ovr == "ollama_remote":
        return True
    if ovr in ("openrouter", "ollama"):
        return False
    return os.getenv("LLM_PROVIDER", "").strip().lower() == "ollama_remote"


def get_ollama_http_settings() -> tuple[str, dict[str, str]]:
    """
    Returns (base_url_without_trailing_slash, headers) for /v1/chat/completions.
    Remote mode uses OLLAMA_REMOTE_* (OpenAI-compatible, e.g. ngrok exposing Ollama).
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if _use_remote_ollama_http():
        base = os.getenv("OLLAMA_REMOTE_BASE_URL", "").strip().rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3].rstrip("/")
        if not base:
            raise ValueError(
                "OLLAMA_REMOTE_BASE_URL is required when using provider ollama_remote "
                "(or LLM_PROVIDER=ollama_remote). Example: https://xxxx.ngrok-free.app "
                "(no /v1 suffix)."
            )
        api_key = os.getenv("OLLAMA_REMOTE_API_KEY", "ollama").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if os.getenv("OLLAMA_REMOTE_NGROK_SKIP", "").strip().lower() in ("1", "true", "yes"):
            headers["ngrok-skip-browser-warning"] = "true"
        return base, headers
    base = ollama_base_url()
    key = os.getenv("OLLAMA_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return base, headers


def resolve_ollama_route(explicit_model: str | None, fallback_default: str) -> tuple[str, str]:
    """
    Decide backend and model string for chat.

    Returns:
        ("ollama", tag) — call Ollama with model `tag`
        ("openrouter", model_id) — call OpenRouter with full model id
    """
    m = (explicit_model or fallback_default or "").strip()
    override = get_llm_provider_override()

    if override == "openrouter":
        if m.lower().startswith("ollama:"):
            tag = m.split(":", 1)[1].strip() or default_ollama_model_tag()
            return "ollama", tag
        return "openrouter", m

    if override == "gemini":
        if not m or not m.startswith("gemini-"):
            return "gemini", os.getenv("DEEPAGENT_MODEL", "gemini-3.1-flash-lite-preview")
        return "gemini", m

    if override == "ollama":
        if m.lower().startswith("ollama:"):
            tag = m.split(":", 1)[1].strip() or default_ollama_model_tag()
            return "ollama", tag
        return "ollama", default_ollama_model_tag()

    if override == "ollama_remote":
        if m.lower().startswith("ollama:"):
            tag = m.split(":", 1)[1].strip() or default_remote_model_tag()
            return "ollama", tag
        return "ollama", default_remote_model_tag()

    low = m.lower()
    if low.startswith("ollama:"):
        tag = m.split(":", 1)[1].strip()
        if not tag:
            tag = default_ollama_model_tag()
        return "ollama", tag
    if os.getenv("LLM_PROVIDER", "").strip().lower() == "ollama":
        return "ollama", default_ollama_model_tag()
    if os.getenv("LLM_PROVIDER", "").strip().lower() == "ollama_remote":
        return "ollama", default_remote_model_tag()
    return "openrouter", m


async def ollama_chat_completion(
    messages: list[dict],
    model_tag: str,
    tools: list[dict] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: dict | None = None,
    timeout: float = 300.0,
) -> dict[str, Any]:
    """POST to Ollama OpenAI-compatible endpoint; returns same top-level shape as OpenRouter."""
    base, headers = get_ollama_http_settings()
    url = f"{base}/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": model_tag,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens > 0:
        payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = tools
    if response_format:
        payload["response_format"] = response_format

    logger.info("[Ollama] POST %s model=%s", url, model_tag)

    async def _post(p: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=p)
            response.raise_for_status()
            data = response.json()
            if "choices" not in data:
                raise ValueError(f"Ollama response missing choices: {str(data)[:400]}")
            return data

    try:
        return await _post(payload)
    except httpx.HTTPStatusError as e:
        if e.response.status_code not in (400, 422):
            logger.error(
                "[Ollama] HTTP %s: %s",
                e.response.status_code,
                (e.response.text or "")[:500],
            )
            raise
        cur: dict[str, Any] = dict(payload)
        if "response_format" in cur:
            logger.warning("[Ollama] Retrying without response_format")
            cur = {k: v for k, v in cur.items() if k != "response_format"}
            try:
                return await _post(cur)
            except httpx.HTTPStatusError as e2:
                if e2.response.status_code not in (400, 422):
                    raise
        if "tools" in cur:
            logger.warning("[Ollama] Retrying without tools (local model may not support tool calls)")
            cur = {k: v for k, v in cur.items() if k != "tools"}
            return await _post(cur)
        raise
