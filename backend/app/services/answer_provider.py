import json
import logging
import re
import time
from collections.abc import Sequence
from urllib.parse import quote

import httpx

from backend.app.core.config import Settings
from backend.app.models.domain import AnswerResult, RetrievedChunk

_WORD_PATTERN = re.compile(r"[a-z0-9][a-z0-9'-]*", re.IGNORECASE)
logger = logging.getLogger(__name__)
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}


class ExtractiveAnswerProvider:
    name = "local-extractive"

    def __init__(self, max_sentences: int = 3) -> None:
        self.max_sentences = max_sentences

    def generate(
        self,
        query: str,
        retrieved_chunks: Sequence[RetrievedChunk],
    ) -> AnswerResult | None:
        query_terms = {
            word.lower() for word in _WORD_PATTERN.findall(query) if word.lower() not in _STOP_WORDS
        }
        if not query_terms:
            query_terms = {word.lower() for word in _WORD_PATTERN.findall(query)}

        ranked: list[tuple[int, int, int, str, str]] = []
        for chunk_order, retrieved in enumerate(retrieved_chunks):
            sentences = re.split(r"(?<=[.!?])\s+", retrieved.chunk.text.strip())
            for sentence_order, sentence in enumerate(sentences):
                sentence_terms = {word.lower() for word in _WORD_PATTERN.findall(sentence)}
                overlap = len(query_terms & sentence_terms)
                if overlap:
                    ranked.append(
                        (
                            -overlap,
                            chunk_order,
                            sentence_order,
                            sentence.strip(),
                            retrieved.chunk.chunk_id,
                        )
                    )

        if not ranked:
            return None

        selected = sorted(ranked)[: self.max_sentences]
        answer = " ".join(item[3] for item in selected)
        source_chunk_ids = tuple(dict.fromkeys(item[4] for item in selected))
        return AnswerResult(answer=answer, source_chunk_ids=source_chunk_ids)


class ProviderError(RuntimeError):
    pass


class RoutedAnswerProvider:
    def __init__(
        self, settings: Settings, local_provider: ExtractiveAnswerProvider | None = None
    ) -> None:
        self.settings = settings
        self.local_provider = local_provider or ExtractiveAnswerProvider()
        self.name = self.local_provider.name
        self._client = httpx.Client(timeout=settings.PROVIDER_TIMEOUT_SECONDS)
        self._endpoint, self._api_key = self._provider_configuration()
        self.name = (
            settings.LLM_PROVIDER if settings.LLM_PROVIDER != "mock" else self.local_provider.name
        )

    def close(self) -> None:
        self._client.close()

    def generate(
        self,
        query: str,
        retrieved_chunks: Sequence[RetrievedChunk],
    ) -> AnswerResult | None:
        if self.settings.LLM_PROVIDER == "mock":
            result = self.local_provider.generate(query, retrieved_chunks)
            if result is None:
                return None
            return AnswerResult(
                answer=result.answer,
                source_chunk_ids=result.source_chunk_ids,
                confidence=result.confidence,
                model_name=self.local_provider.name,
                provider_name=self.local_provider.name,
            )

        total_cost = 0.0
        first = self._request(query, retrieved_chunks, self.settings.CHEAP_MODEL_NAME)
        total_cost += self._cost(first, strong=False)
        selected = first
        input_tokens = first.input_tokens
        output_tokens = first.output_tokens
        escalated = False
        if (
            first.confidence < self.settings.CONFIDENCE_THRESHOLD
            and self.settings.ESCALATION_ENABLED
        ):
            for _ in range(self.settings.MAX_ESCALATION_RETRIES):
                escalated = True
                selected = self._request(query, retrieved_chunks, self.settings.STRONG_MODEL_NAME)
                total_cost += self._cost(selected, strong=True)
                input_tokens += selected.input_tokens
                output_tokens += selected.output_tokens
                if selected.confidence >= self.settings.CONFIDENCE_THRESHOLD:
                    break
        return AnswerResult(
            answer=selected.answer,
            source_chunk_ids=selected.source_chunk_ids,
            confidence=selected.confidence,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_name=selected.model_name,
            provider_name=self.settings.LLM_PROVIDER,
            route="strong" if selected is not first else "cheap",
            escalated=escalated,
            cost_usd=total_cost,
        )

    def _provider_configuration(self) -> tuple[str, str | None]:
        provider = self.settings.LLM_PROVIDER
        if provider == "mock":
            return "", None
        if provider == "openai":
            return "https://api.openai.com/v1/chat/completions", self.settings.OPENAI_API_KEY
        if provider == "groq":
            return "https://api.groq.com/openai/v1/chat/completions", self.settings.GROQ_API_KEY
        if provider == "gemini":
            return "", self.settings.GEMINI_API_KEY
        if provider == "ollama":
            return f"{self.settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat", None
        raise ValueError("Unsupported answer provider.")

    def _request(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        model: str,
    ) -> AnswerResult:
        if self.settings.LLM_PROVIDER != "ollama" and not self._api_key:
            raise ProviderError("The configured answer provider is missing its API key.")
        prompt = self._prompt(query, chunks)
        for attempt in range(self.settings.PROVIDER_RETRY_COUNT + 1):
            try:
                result = (
                    self._request_gemini(model, prompt, chunks)
                    if self.settings.LLM_PROVIDER == "gemini"
                    else self._request_chat(model, prompt, chunks)
                )
                return result
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self.settings.PROVIDER_RETRY_COUNT:
                    logger.warning("Configured answer provider timed out or was unavailable.")
                    raise ProviderError("The configured answer provider is unavailable.") from exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500 and exc.response.status_code != 429:
                    logger.warning(
                        "Configured answer provider rejected a request (status %s).",
                        exc.response.status_code,
                    )
                    raise ProviderError(
                        "The configured answer provider rejected the request."
                    ) from exc
                if attempt >= self.settings.PROVIDER_RETRY_COUNT:
                    logger.warning("Configured answer provider returned a transient error.")
                    raise ProviderError("The configured answer provider is unavailable.") from exc
            except (ValueError, KeyError, TypeError) as exc:
                logger.warning("Configured answer provider returned an invalid response.")
                raise ProviderError(
                    "The configured answer provider returned an invalid response."
                ) from exc
            time.sleep(min(0.1 * (2**attempt), 1.0))
        raise ProviderError("The configured answer provider is unavailable.")

    def _request_chat(
        self,
        model: str,
        prompt: str,
        chunks: Sequence[RetrievedChunk],
    ) -> AnswerResult:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if self.settings.LLM_PROVIDER == "ollama":
            response = self._client.post(
                self._endpoint,
                headers=headers,
                json={
                    "model": model,
                    "stream": False,
                    "format": "json",
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            body = response.json()
            content = body["message"]["content"]
            usage = (body.get("prompt_eval_count", 0), body.get("eval_count", 0))
        else:
            response = self._client.post(
                self._endpoint,
                headers=headers,
                json={
                    "model": model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            token_usage = body.get("usage", {})
            usage = (token_usage.get("prompt_tokens", 0), token_usage.get("completion_tokens", 0))
        return self._parse_content(content, chunks, model, usage)

    def _request_gemini(
        self,
        model: str,
        prompt: str,
        chunks: Sequence[RetrievedChunk],
    ) -> AnswerResult:
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(model, safe='')}:generateContent"
        )
        response = self._client.post(
            endpoint,
            headers={"x-goog-api-key": self._api_key or ""},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
            },
        )
        response.raise_for_status()
        body = response.json()
        content = body["candidates"][0]["content"]["parts"][0]["text"]
        usage = body.get("usageMetadata", {})
        return self._parse_content(
            content,
            chunks,
            model,
            (usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0)),
        )

    @staticmethod
    def _prompt(query: str, chunks: Sequence[RetrievedChunk]) -> str:
        evidence = [
            {
                "chunk_id": item.chunk.chunk_id,
                "text": item.chunk.text,
            }
            for item in chunks
        ]
        return (
            "Answer using only the supplied evidence. Return one JSON object with keys "
            '"answer" (string), "source_chunk_ids" (array of supplied chunk_id values), '
            'and "confidence" (number from 0 to 1). Do not include unsupported claims.\n'
            f"Question: {query}\nEvidence: {json.dumps(evidence, ensure_ascii=True)}"
        )

    @staticmethod
    def _parse_content(
        content: str,
        chunks: Sequence[RetrievedChunk],
        model: str,
        usage: tuple[int, int],
    ) -> AnswerResult:
        data = json.loads(content)
        allowed_ids = {item.chunk.chunk_id for item in chunks}
        answer = data["answer"]
        source_ids = data["source_chunk_ids"]
        confidence = data["confidence"]
        if (
            not isinstance(answer, str)
            or not answer.strip()
            or not isinstance(source_ids, list)
            or any(not isinstance(item, str) or item not in allowed_ids for item in source_ids)
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise ValueError("Invalid answer-provider output.")
        source_ids = list(dict.fromkeys(source_ids))
        if not source_ids:
            raise ValueError("Answer provider did not cite evidence.")
        return AnswerResult(
            answer=answer.strip(),
            source_chunk_ids=tuple(source_ids),
            confidence=float(confidence),
            input_tokens=int(usage[0] or 0),
            output_tokens=int(usage[1] or 0),
            model_name=model,
        )

    def _cost(self, result: AnswerResult, strong: bool) -> float:
        input_price = (
            self.settings.STRONG_MODEL_INPUT_PRICE_PER_1M
            if strong
            else self.settings.CHEAP_MODEL_INPUT_PRICE_PER_1M
        )
        output_price = (
            self.settings.STRONG_MODEL_OUTPUT_PRICE_PER_1M
            if strong
            else self.settings.CHEAP_MODEL_OUTPUT_PRICE_PER_1M
        )
        return (result.input_tokens * input_price + result.output_tokens * output_price) / 1_000_000
