from dataclasses import dataclass


@dataclass(frozen=True)
class LoadedDocument:
    document_id: str
    source_path: str
    text: str


@dataclass(frozen=True)
class DocumentChunk:
    document_id: str
    chunk_id: str
    source_path: str
    corpus_version: str
    text: str
    token_count: int


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: DocumentChunk
    score: float


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    source_chunk_ids: tuple[str, ...]
    confidence: float = 1.0
    input_tokens: int = 0
    output_tokens: int = 0
    model_name: str | None = None
    provider_name: str | None = None
    route: str = "cheap"
    escalated: bool = False
    cost_usd: float = 0.0
