"""Tests for core.openrouter — LLM client with fallback."""
import pytest
from core.openrouter import OpenRouterClient, FREE_MODEL_CHAIN


def test_client_init_with_no_keys(monkeypatch):
    monkeypatch.setattr("core.openrouter._API_KEYS", [])
    monkeypatch.setattr("core.openrouter.OPENROUTER_API_KEY", "")
    client = OpenRouterClient()
    assert client.api_keys == []


def test_free_model_chain_not_empty():
    assert len(FREE_MODEL_CHAIN) >= 3


def test_make_headers():
    client = OpenRouterClient()
    headers = client._make_headers("test-key")
    assert headers["Authorization"] == "Bearer test-key"
    assert "Content-Type" in headers


def test_select_model():
    client = OpenRouterClient()
    assert client.select_model("simple") != ""
    assert client.select_model("complex") != ""
    assert client.select_model("nonexistent") != ""
