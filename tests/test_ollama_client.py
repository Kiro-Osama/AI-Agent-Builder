"""Tests for Ollama routing and client helpers (stdlib only)."""
import os
import unittest

from core import ollama_client
from core.ollama_client import use_llm_provider


class TestResolveOllamaRoute(unittest.TestCase):
    def tearDown(self) -> None:
        for k in (
            "LLM_PROVIDER",
            "OLLAMA_MODEL",
            "OLLAMA_REMOTE_BASE_URL",
            "OLLAMA_REMOTE_MODEL",
            "OLLAMA_REMOTE_API_KEY",
        ):
            os.environ.pop(k, None)

    def test_ollama_prefix(self) -> None:
        backend, tag = ollama_client.resolve_ollama_route("ollama:my-model", "google/x:free")
        self.assertEqual(backend, "ollama")
        self.assertEqual(tag, "my-model")

    def test_ollama_prefix_empty_uses_default(self) -> None:
        backend, tag = ollama_client.resolve_ollama_route("ollama:", "google/x:free")
        self.assertEqual(backend, "ollama")
        self.assertEqual(tag, ollama_client.default_ollama_model_tag())

    def test_openrouter(self) -> None:
        backend, mid = ollama_client.resolve_ollama_route("google/gemma:free", "google/x:free")
        self.assertEqual(backend, "openrouter")
        self.assertEqual(mid, "google/gemma:free")

    def test_llm_provider_ollama(self) -> None:
        os.environ["LLM_PROVIDER"] = "ollama"
        os.environ["OLLAMA_MODEL"] = "qwen3.5:4b-q4_K_M"
        backend, tag = ollama_client.resolve_ollama_route("google/ignored:free", "google/x:free")
        self.assertEqual(backend, "ollama")
        self.assertEqual(tag, "qwen3.5:4b-q4_K_M")

    def test_ui_override_openrouter_beats_env_ollama(self) -> None:
        os.environ["LLM_PROVIDER"] = "ollama"
        with use_llm_provider("openrouter"):
            b, m = ollama_client.resolve_ollama_route("google/gemma:free", "google/x")
            self.assertEqual(b, "openrouter")
            self.assertEqual(m, "google/gemma:free")

    def test_ui_override_ollama_beats_openrouter_model(self) -> None:
        os.environ.pop("LLM_PROVIDER", None)
        with use_llm_provider("ollama"):
            b, tag = ollama_client.resolve_ollama_route("google/gemma:free", "google/x")
            self.assertEqual(b, "ollama")
            self.assertTrue(tag)

    def test_ui_override_ollama_remote_uses_remote_model_env(self) -> None:
        os.environ["OLLAMA_REMOTE_BASE_URL"] = "https://tunnel.example"
        os.environ["OLLAMA_REMOTE_MODEL"] = "qwen3.5:4b"
        with use_llm_provider("ollama_remote"):
            b, tag = ollama_client.resolve_ollama_route(None, "google/x")
            self.assertEqual(b, "ollama")
            self.assertEqual(tag, "qwen3.5:4b")

    def test_remote_http_settings_require_base_url(self) -> None:
        os.environ.pop("OLLAMA_REMOTE_BASE_URL", None)
        with use_llm_provider("ollama_remote"):
            with self.assertRaises(ValueError):
                ollama_client.get_ollama_http_settings()

    def test_remote_base_url_strips_trailing_v1(self) -> None:
        os.environ["OLLAMA_REMOTE_BASE_URL"] = "https://ex.ngrok-free.app/v1"
        with use_llm_provider("ollama_remote"):
            base, h = ollama_client.get_ollama_http_settings()
            self.assertEqual(base, "https://ex.ngrok-free.app")
            self.assertIn("Authorization", h)
