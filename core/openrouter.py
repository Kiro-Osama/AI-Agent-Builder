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
DEFAULT_CHAT_MODEL = os.getenv("DEFAULT_CHAT_MODEL", "google/gemma-4-26b-a4b-it:free")

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
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds


class OpenRouterClient:
    """Client for OpenRouter API - multi-model gateway."""

    def __init__(self):
        self.base_url = OPENROUTER_BASE_URL
        self.api_key = OPENROUTER_API_KEY
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
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
        Send a chat completion request to OpenRouter with automatic retry
        and model fallback on 429.
        """
        primary_model = model or DEFAULT_CHAT_MODEL

        # Build the fallback list: primary first, then chain (excluding dupes)
        models_to_try = [primary_model]
        for m in FREE_MODEL_CHAIN:
            if m != primary_model:
                models_to_try.append(m)

        last_error: Exception | None = None

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
                            headers=self.headers,
                            json=payload,
                        )
                        response.raise_for_status()
                        return response.json()

                except httpx.HTTPStatusError as e:
                    last_error = e
                    status = e.response.status_code

                    if status == 429:
                        delay = RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            "429 from %s (attempt %d/%d) — retrying in %.1fs",
                            model_id, attempt + 1, MAX_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                        continue

                    if status == 400:
                        # Invalid model or bad request — skip to next model immediately
                        logger.warning("400 from %s — skipping to next model", model_id)
                        break  # break retry loop, move to next model

                    logger.error("OpenRouter API error: %s - %s", status, e.response.text)
                    raise
                except Exception as e:
                    logger.error("OpenRouter request failed: %s", e)
                    raise

            # All retries exhausted for this model — move to next
            logger.warning("All %d retries exhausted for %s, trying next model...", MAX_RETRIES, model_id)

        # Every model in the chain failed
        logger.error("All models exhausted after retries. Last error: %s", last_error)
        raise last_error or RuntimeError("All models in fallback chain returned 429")

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
        message = result["choices"][0]["message"]

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
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/models",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json().get("data", [])


# -----------------------------------------------
# Singleton instance
# -----------------------------------------------
openrouter_client = OpenRouterClient()
