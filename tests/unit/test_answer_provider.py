import json

import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.models.domain import AnswerResult, DocumentChunk, RetrievedChunk
from backend.app.services.answer_provider import (
    ExtractiveAnswerProvider,
    ProviderError,
    RoutedAnswerProvider,
)


def test_extractive_provider_returns_only_matching_sentences_and_sources() -> None:
    chunk = DocumentChunk(
        document_id="doc-1",
        chunk_id="doc-1:0",
        source_path="rag-basics.txt",
        corpus_version="version-1",
        text=("RAG combines document retrieval with generation. The sky is blue on a clear day."),
        token_count=15,
    )

    answer = ExtractiveAnswerProvider().generate(
        "How does RAG combine retrieval?",
        [RetrievedChunk(chunk=chunk, score=0.9)],
    )

    assert answer is not None
    assert answer.answer == "RAG combines document retrieval with generation."
    assert answer.source_chunk_ids == ("doc-1:0",)


def test_extractive_provider_declines_when_no_sentence_matches() -> None:
    chunk = DocumentChunk(
        document_id="doc-1",
        chunk_id="doc-1:0",
        source_path="rag-basics.txt",
        corpus_version="version-1",
        text="The forest contains many evergreen trees.",
        token_count=7,
    )

    answer = ExtractiveAnswerProvider().generate(
        "How does the database store a vector?",
        [RetrievedChunk(chunk=chunk, score=0.9)],
    )

    assert answer is None


def test_routed_provider_escalates_and_calculates_provider_reported_cost() -> None:
    settings = Settings(
        _env_file=None,
        LLM_PROVIDER="openai",
        OPENAI_API_KEY="test-key-not-used-for-network",
        CONFIDENCE_THRESHOLD=0.7,
        PROVIDER_RETRY_COUNT=0,
    )

    class MockRoutedProvider(RoutedAnswerProvider):
        def __init__(self, provider_settings: Settings) -> None:
            super().__init__(provider_settings)
            self.models: list[str] = []

        def _request(self, query: str, chunks: list[RetrievedChunk], model: str) -> AnswerResult:
            del query, chunks
            self.models.append(model)
            if model == settings.CHEAP_MODEL_NAME:
                return AnswerResult("Draft answer.", ("chunk-1",), 0.4, 100, 50, model)
            return AnswerResult("Final answer.", ("chunk-1",), 0.9, 200, 100, model)

    provider = MockRoutedProvider(settings)
    result = provider.generate("What is RAG?", [])
    provider.close()

    assert result is not None
    assert provider.models == [settings.CHEAP_MODEL_NAME, settings.STRONG_MODEL_NAME]
    assert result.route == "strong"
    assert result.escalated is True
    assert result.input_tokens == 300
    assert result.output_tokens == 150
    assert result.cost_usd == pytest.approx(0.001545)


def test_provider_retries_transient_timeout_without_logging_request_content() -> None:
    settings = Settings(
        _env_file=None,
        LLM_PROVIDER="openai",
        OPENAI_API_KEY="test-key-not-used-for-network",
        PROVIDER_RETRY_COUNT=1,
    )
    provider = RoutedAnswerProvider(settings)
    calls = 0

    def mock_request_chat(model: str, prompt: str, chunks: list[RetrievedChunk]) -> AnswerResult:
        nonlocal calls
        del model, prompt, chunks
        calls += 1
        if calls == 1:
            raise httpx.TimeoutException("secret query should not appear in logs")
        return AnswerResult("Safe answer.", ("chunk-1",), 0.9, 10, 2, "cheap")

    provider._request_chat = mock_request_chat
    try:
        chunk = RetrievedChunk(
            DocumentChunk("doc", "chunk-1", "safe.txt", "version", "Safe evidence.", 2),
            0.9,
        )
        answer = provider._request("private query text", [chunk], "cheap")
    finally:
        provider.close()

    assert calls == 2
    assert answer.answer == "Safe answer."


def test_provider_fails_after_retry_budget() -> None:
    settings = Settings(
        _env_file=None,
        LLM_PROVIDER="openai",
        OPENAI_API_KEY="test-key-not-used-for-network",
        PROVIDER_RETRY_COUNT=0,
    )
    provider = RoutedAnswerProvider(settings)
    provider._request_chat = lambda model, prompt, chunks: (_ for _ in ()).throw(
        httpx.TimeoutException("timeout")
    )
    try:
        chunk = RetrievedChunk(
            DocumentChunk("doc", "chunk-1", "safe.txt", "version", "Safe evidence.", 2),
            0.9,
        )
        with pytest.raises(ProviderError, match="unavailable"):
            provider._request("private query text", [chunk], "cheap")
    finally:
        provider.close()


def test_openai_adapter_uses_mock_transport_and_provider_token_usage() -> None:
    settings = Settings(
        _env_file=None,
        LLM_PROVIDER="openai",
        OPENAI_API_KEY="mock-transport-key",
        PROVIDER_RETRY_COUNT=0,
    )
    provider = RoutedAnswerProvider(settings)
    provider._client.close()
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["model"] == settings.CHEAP_MODEL_NAME
        assert "Private test question" in payload["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": "Evidence-based answer.",
                                    "source_chunk_ids": ["chunk-1"],
                                    "confidence": 0.91,
                                }
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 25, "completion_tokens": 8},
            },
        )

    provider._client = httpx.Client(transport=httpx.MockTransport(respond))
    chunk = RetrievedChunk(
        DocumentChunk("doc", "chunk-1", "safe.txt", "version", "Relevant evidence.", 2),
        0.9,
    )
    try:
        result = provider._request("Private test question?", [chunk], settings.CHEAP_MODEL_NAME)
    finally:
        provider.close()

    assert len(requests) == 1
    assert requests[0].url.host == "api.openai.com"
    assert result.answer == "Evidence-based answer."
    assert result.source_chunk_ids == ("chunk-1",)
    assert result.input_tokens == 25
    assert result.output_tokens == 8
