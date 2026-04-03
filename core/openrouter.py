"""
OpenRouter API Client
=====================
Multi-model gateway for chat completions and model selection.
"""
import os
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# -----------------------------------------------
# Configuration
# -----------------------------------------------
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
DEFAULT_CHAT_MODEL = os.getenv("DEFAULT_CHAT_MODEL", "openrouter/free")

# -----------------------------------------------
# Model complexity mapping
# -----------------------------------------------
MODEL_TIERS = {
    "simple": "nvidia/nemotron-3-super-120b-a12b:free",
    "medium": "nvidia/nemotron-3-super-120b-a12b:free",
    "complex": "nvidia/nemotron-3-super-120b-a12b:free",
    "creative": "nvidia/nemotron-3-super-120b-a12b:free",
}


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
        Send a chat completion request to OpenRouter.

        Args:
            messages: List of message dicts [{"role": "...", "content": "..."}]
            model: OpenRouter model ID (defaults to DEFAULT_CHAT_MODEL)
            tools: Optional tool definitions for function calling
            temperature: Sampling temperature
            max_tokens: Maximum response tokens
            response_format: Optional response format (e.g., {"type": "json_object"})

        Returns:
            Full API response dict
        """
        model = model or DEFAULT_CHAT_MODEL

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            payload["tools"] = tools
        if response_format:
            payload["response_format"] = response_format

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"OpenRouter API error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"OpenRouter request failed: {e}")
                raise

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
    ) -> dict:
        """Convenience method that parses JSON from the response. Very robust parsing."""
        import re

        result = await self.chat_completion(
            messages,
            model=model,
            temperature=temperature,
        )
        content = result["choices"][0]["message"]["content"]
        
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
            match = re.search(r'\{[\s\S]*\}', content)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass
        
        # Try fixing common issues: single quotes, trailing commas
        try:
            # Replace single quotes with double quotes (risky but sometimes works)
            fixed = content.replace("'", '"')
            # Remove trailing commas before } or ]
            fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
            match = re.search(r'\{[\s\S]*\}', fixed)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass
        
        logger.error(f"Failed to parse JSON. Raw output: {content[:500]}")
        raise ValueError(f"Model returned invalid JSON")

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
