from app.domains.ingestion.chunkers.base import BaseChunker
from app.domains.ingestion.schemas import ChunkData, ParsedDocument


class FixedChunker(BaseChunker):
    """Token-based chunking with overlap, splitting at sentence boundaries where possible."""

    def chunk(
        self,
        parsed: ParsedDocument,
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[ChunkData]:
        # Concatenate all element text with page tracking
        full_text_parts: list[tuple[str, int | None]] = []
        for page in parsed.pages:
            for el in page.elements:
                full_text_parts.append((el.content, el.page_number or page.page_number))

        sentences: list[tuple[str, int | None]] = []
        for text, page_num in full_text_parts:
            for sentence in self.split_sentences(text):
                # A single "sentence" (e.g. no punctuation) can still exceed the
                # chunk budget — break it into word-bounded pieces so it's chunkable.
                if self.count_tokens(sentence) > chunk_size:
                    for piece in self._split_oversized_text(sentence, chunk_size):
                        sentences.append((piece, page_num))
                else:
                    sentences.append((sentence, page_num))

        chunks: list[ChunkData] = []
        current_sentences: list[str] = []
        current_page: int | None = None
        current_tokens = 0
        chunk_index = 0

        i = 0
        while i < len(sentences):
            sentence, page_num = sentences[i]
            sentence_tokens = self.count_tokens(sentence)

            if current_tokens + sentence_tokens > chunk_size and current_sentences:
                # Flush current chunk
                content = " ".join(current_sentences)
                chunks.append(
                    ChunkData(
                        content=content,
                        chunk_index=chunk_index,
                        token_count=current_tokens,
                        metadata={"page_number": current_page},
                    )
                )
                chunk_index += 1

                # Build overlap from the tail of the current chunk
                overlap_sentences: list[str] = []
                overlap_tokens = 0
                for s in reversed(current_sentences):
                    t = self.count_tokens(s)
                    if overlap_tokens + t > chunk_overlap:
                        break
                    overlap_sentences.insert(0, s)
                    overlap_tokens += t

                current_sentences = overlap_sentences
                current_tokens = overlap_tokens
                current_page = page_num
                continue  # re-process this sentence against the new (overlapped) chunk

            current_sentences.append(sentence)
            current_tokens += sentence_tokens
            if current_page is None:
                current_page = page_num
            i += 1

        if current_sentences:
            content = " ".join(current_sentences)
            chunks.append(
                ChunkData(
                    content=content,
                    chunk_index=chunk_index,
                    token_count=current_tokens,
                    metadata={"page_number": current_page},
                )
            )

        return chunks

    def _split_oversized_text(self, text: str, chunk_size: int) -> list[str]:
        """Break text with no usable sentence boundaries into word-bounded pieces."""
        words = text.split(" ")
        pieces: list[str] = []
        current: list[str] = []
        current_tokens = 0

        for word in words:
            word_tokens = self.count_tokens(word + " ")
            if current_tokens + word_tokens > chunk_size and current:
                pieces.append(" ".join(current))
                current = []
                current_tokens = 0
            current.append(word)
            current_tokens += word_tokens

        if current:
            pieces.append(" ".join(current))

        return pieces
