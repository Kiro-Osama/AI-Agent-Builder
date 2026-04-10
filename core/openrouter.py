"""
OpenRouter API Client
=====================
Multi-model gateway for chat completions and model selection.
Includes automatic retry with exponential backoff and model fallback
for 429 (rate-limit) errors.
"""
import asyncio
import os
import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# -----------------------------------------------
# Configuration (env-driven; no secrets in repo)
# -----------------------------------------------
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_API_KEY_BACKUP = os.getenv("OPENROUTER_API_KEY_BACKUP", "")
DEFAULT_CHAT_MODEL = os.getenv("DEFAULT_CHAT_MODEL", "google/gemma-4-26b-a4b-it:free")

# All available API keys (primary + backup) for rotation on 429
_API_KEYS: list[str] = [k for k in [OPENROUTER_API_KEY, OPENROUTER_API_KEY_BACKUP] if k]

# Ordered fallback chain: if the primary model fails (429/400), try the next one.
FREE_MODEL_CHAIN: list[str] = [
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
]

# -----------------------------------------------
# Model complexity mapping (override per tier via env)
# -----------------------------------------------
MODEL_TIERS = {
    "simple": os.getenv(
        "OPENROUTER_MODEL_SIMPLE",
        "meta-llama/llama-3.3-70b-instruct:free",
    ),
    "medium": os.getenv("OPENROUTER_MODEL_MEDIUM", "google/gemma-4-26b-a4b-it:free"),
    "complex": os.getenv("OPENROUTER_MODEL_COMPLEX", "qwen/qwen3-next-80b-a3b-instruct:free"),
    "creative": os.getenv("OPENROUTER_MODEL_CREATIVE", "google/gemma-4-31b-it:free"),
}

# Retry settings
MAX_RETRIES = 2
RETRY_BASE_DELAY = 3.0  # seconds
MAX_RETRY_DELAY = 15.0  # cap to avoid 120s waits


class OpenRouterClient:
    """Client for OpenRouter API — multi-model gateway with key rotation."""

    def __init__(self):
        self.base_url = OPENROUTER_BASE_URL
        self.api_keys = [k for k in _API_KEYS if k.strip()] if _API_KEYS else []
        if not self.api_keys:
            logger.warning(
                "No OpenRouter API keys configured. Set OPENROUTER_API_KEY in .env. "
                "LLM calls will fail."
            )
        self._current_key_idx = 0

    def _make_headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://agent-builder.local",
            "X-Title": "Agent Builder V5",
        }

    async def chat_completion(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> dict[str, Any]:
        """
        Send a chat completion request with:
        1. API key rotation (primary → backup on 429 daily-limit)
        2. Model fallback chain (on 429 per-model or 400 invalid model)
        3. Exponential backoff retry per model
        """
        if not self.api_keys:
            raise RuntimeError(
                "No OpenRouter API keys configured. Set OPENROUTER_API_KEY in .env"
            )

        primary_model = model or DEFAULT_CHAT_MODEL

        models_to_try = [primary_model]
        for m in FREE_MODEL_CHAIN:
            if m != primary_model:
                models_to_try.append(m)

        last_error: Exception | None = None

        for key_idx, api_key in enumerate(self.api_keys):
            headers = self._make_headers(api_key)
            key_label = "primary" if key_idx == 0 else "backup"

            for model_id in models_to_try:
                for attempt in range(MAX_RETRIES):
                    payload = {
                        "model": model_id,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                    if tools:
                        payload["tools"] = tools
                    if response_format:
                        payload["response_format"] = response_format

                    try:
                        async with httpx.AsyncClient(timeout=120.0) as client:
                            response = await client.post(
                                f"{self.base_url}/chat/completions",
                                headers=headers,
                                json=payload,
                            )
                            response.raise_for_status()
                            data = response.json()
                            if "choices" not in data:
                                logger.warning(
                                    "No 'choices' in response from %s/%s: %s",
                                    key_label, model_id, str(data)[:300],
                                )
                                break  # skip to next model
                            return data

                    except httpx.HTTPStatusError as e:
                        last_error = e
                        status = e.response.status_code
                        body = e.response.text

                        if status == 429:
                            if "free-models-per-day" in body:
                                logger.warning(
                                    "Daily limit hit on %s key — switching keys", key_label,
                                )
                                break

                            delay = min(RETRY_BASE_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
                            logger.warning(
                                "429 from %s/%s (attempt %d/%d) — %.1fs",
                                key_label, model_id, attempt + 1, MAX_RETRIES, delay,
                            )
                            await asyncio.sleep(delay)
                            continue

                        if status == 400:
                            logger.warning("400 from %s — skipping to next model", model_id)
                            break

                        logger.error("OpenRouter API error: %s - %s", status, body)
                        raise
                    except Exception as e:
                        logger.error("OpenRouter request failed: %s", e)
                        raise

                else:
                    # Retry loop finished without break → all retries used
                    logger.warning("Retries exhausted for %s/%s", key_label, model_id)
                    continue  # try next model

                # If we broke out of retry loop due to daily limit, break model loop too
                if last_error and getattr(last_error, "response", None) is not None:
                    resp_text = last_error.response.text
                    if last_error.response.status_code == 429 and "free-models-per-day" in resp_text:
                        break  # break model loop → next key

        logger.error("All keys + models exhausted. Last error: %s", last_error)
        raise last_error or RuntimeError("All API keys and models exhausted")

    async def chat_completion_text(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        """Convenience method that returns just the text content."""
        result = await self.chat_completion(messages, model=model, temperature=temperature)
        return result["choices"][0]["message"]["content"]

    async def chat_completion_json(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> dict:
        """Convenience method that parses JSON from the response. Very robust parsing."""
        kwargs: dict = {"model": model, "temperature": temperature}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        result = await self.chat_completion(messages, **kwargs)
        choices = result.get("choices")
        if not choices:
            raise ValueError(f"No choices in API response: {str(result)[:300]}")
        message = choices[0]["message"]

        # Some models return content=null when they emit tool_calls instead.
        # Extract text from tool_call arguments as a fallback.
        content = message.get("content") or ""
        if not content and message.get("tool_calls"):
            try:
                content = message["tool_calls"][0]["function"]["arguments"]
            except (KeyError, IndexError, TypeError):
                pass
        if not content:
            raise ValueError(
                f"Model returned no text content. finish_reason="
                f"{result['choices'][0].get('finish_reason')} model={result.get('model')}"
            )

        # Strip markdown formatting if present
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]

        if content.endswith("```"):
            content = content[:-3]

        content = content.strip()

        # Try direct parse first
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON object from surrounding text
        try:
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass

        # Try fixing common issues: single quotes, trailing commas
        try:
            fixed = content.replace("'", '"')
            fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
            match = re.search(r"\{[\s\S]*\}", fixed)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass

        logger.error(f"Failed to parse JSON. Raw output: {content[:500]}")
        raise ValueError("Model returned invalid JSON")

    def select_model(self, task_complexity: str = "medium") -> str:
        """
        Select the best model based on task complexity.

        Args:
            task_complexity: One of 'simple', 'medium', 'complex', 'creative'

        Returns:
            OpenRouter model ID
        """
        return MODEL_TIERS.get(task_complexity, DEFAULT_CHAT_MODEL)

    async def get_available_models(self) -> list[dict]:
        """Fetch list of available models from OpenRouter."""
        if not self.api_keys:
            return []
        headers = self._make_headers(self.api_keys[0])
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/models",
                headers=headers,
            )
            response.raise_for_status()
            return response.json().get("data", [])


# -----------------------------------------------
# Singleton instance
# -----------------------------------------------
openrouter_client = OpenRouterClient()
