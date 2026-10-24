from collections.abc import Sequence
from typing import Protocol

from backend.app.models.domain import DocumentChunk, LoadedDocument


class Tokenizer(Protocol):
    def encode(
        self,
        text: str,
        *,
        add_special_tokens: bool = False,
        truncation: bool = False,
    ) -> list[int]: ...

    def decode(
        self,
        token_ids: Sequence[int],
        *,
        skip_special_tokens: bool = True,
        clean_up_tokenization_spaces: bool = True,
    ) -> str: ...


class TextChunker:
    def __init__(self, tokenizer: Tokenizer, chunk_size_tokens: int, overlap_tokens: int) -> None:
        if chunk_size_tokens <= 0:
            raise ValueError("chunk_size_tokens must be positive")
        if overlap_tokens < 0 or overlap_tokens >= chunk_size_tokens:
            raise ValueError("overlap_tokens must be non-negative and smaller than chunk size")
        self.tokenizer = tokenizer
        self.chunk_size_tokens = chunk_size_tokens
        self.overlap_tokens = overlap_tokens

    def split(
        self,
        document: LoadedDocument,
        corpus_version: str,
    ) -> list[DocumentChunk]:
        token_ids = self.tokenizer.encode(
            document.text,
            add_special_tokens=False,
            truncation=False,
        )
        if not token_ids:
            return []

        chunks: list[DocumentChunk] = []
        step = self.chunk_size_tokens - self.overlap_tokens
        for index, start in enumerate(range(0, len(token_ids), step)):
            chunk_tokens = token_ids[start : start + self.chunk_size_tokens]
            text = self.tokenizer.decode(
                chunk_tokens,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=True,
            ).strip()
            if text:
                chunks.append(
                    DocumentChunk(
                        document_id=document.document_id,
                        chunk_id=f"{document.document_id}:{index}",
                        source_path=document.source_path,
                        corpus_version=corpus_version,
                        text=text,
                        token_count=len(chunk_tokens),
                    )
                )
            if start + self.chunk_size_tokens >= len(token_ids):
                break
        return chunks

    def split_documents(
        self,
        documents: list[LoadedDocument],
        corpus_version: str,
    ) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        for document in documents:
            chunks.extend(self.split(document, corpus_version))
        return chunks
