from backend.app.models.domain import LoadedDocument
from backend.app.services.chunking import TextChunker


class WordTokenizer:
    def __init__(self) -> None:
        self._word_to_id: dict[str, int] = {}
        self._id_to_word: dict[int, str] = {}

    def encode(
        self,
        text: str,
        *,
        add_special_tokens: bool = False,
        truncation: bool = False,
    ) -> list[int]:
        del add_special_tokens, truncation
        token_ids: list[int] = []
        for word in text.split():
            if word not in self._word_to_id:
                token_id = len(self._word_to_id)
                self._word_to_id[word] = token_id
                self._id_to_word[token_id] = word
            token_ids.append(self._word_to_id[word])
        return token_ids

    def decode(
        self,
        token_ids: list[int],
        *,
        skip_special_tokens: bool = True,
        clean_up_tokenization_spaces: bool = True,
    ) -> str:
        del skip_special_tokens, clean_up_tokenization_spaces
        return " ".join(self._id_to_word[token_id] for token_id in token_ids)


def test_chunker_applies_configured_size_and_overlap() -> None:
    chunker = TextChunker(WordTokenizer(), chunk_size_tokens=4, overlap_tokens=1)
    document = LoadedDocument("doc-1", "guide.txt", "one two three four five six seven")

    chunks = chunker.split(document, "version-1")

    assert [chunk.token_count for chunk in chunks] == [4, 4]
    assert chunks[0].text.split()[-1] == chunks[1].text.split()[0]
    assert chunks[0].chunk_id == "doc-1:0"
    assert chunks[1].corpus_version == "version-1"


def test_chunker_returns_no_chunks_for_empty_text() -> None:
    chunker = TextChunker(WordTokenizer(), chunk_size_tokens=4, overlap_tokens=1)
    document = LoadedDocument("doc-1", "empty.txt", "")

    assert chunker.split(document, "version-1") == []
