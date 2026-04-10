"""
Embedding Generation Module (Google Gemini API)
=================================================
Uses Google AI Studio text-embedding-004 (FREE tier: 1500 req/day).
Vector dimension: 768
"""
import os
import logging

import httpx

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
EMBEDDING_DIMENSION = 768


class EmbeddingGenerator:
    """Generate embeddings using Google Gemini API (FREE tier)."""

    def __init__(self):
        self.api_key = GEMINI_API_KEY
        self.model = GEMINI_EMBEDDING_MODEL
        self.dimension = EMBEDDING_DIMENSION

    async def generate(self, text: str) -> list[float]:
        """
        Generate a 768-dim embedding vector for a single text.
        """
        url = f"{GEMINI_BASE_URL}/models/{self.model}:embedContent?key={self.api_key}"

        payload = {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": self.dimension
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["embedding"]["values"]
            except httpx.HTTPStatusError as e:
                logger.error(f"Gemini Embedding API error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Embedding generation failed: {e}")
                raise

    async def generate_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.
        Uses batchEmbedContents for efficiency.
        """
        url = f"{GEMINI_BASE_URL}/models/{self.model}:batchEmbedContents?key={self.api_key}"

        requests_list = [
            {
                "model": f"models/{self.model}",
                "content": {"parts": [{"text": t}]}
            }
            for t in texts
        ]

        payload = {"requests": requests_list}

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return [item["values"] for item in data["embeddings"]]
            except Exception as e:
                logger.error(f"Batch embedding failed: {e}")
                raise

    def generate_sync(self, text: str) -> list[float]:
        """Synchronous version for startup scripts."""
        import httpx as httpx_sync

        url = f"{GEMINI_BASE_URL}/models/{self.model}:embedContent?key={self.api_key}"
        payload = {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": self.dimension,
        }

        response = httpx_sync.post(url, json=payload, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        return data["embedding"]["values"]


# Singleton
embedding_generator = EmbeddingGenerator()
