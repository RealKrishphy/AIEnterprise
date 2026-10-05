import io
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass

from docx import Document as WordDocument
from pypdf import PdfReader


@dataclass(frozen=True)
class TextChunk:
    index: int
    heading: str | None
    content: str


def extract_text(filename: str, content: bytes) -> str:
    extension = filename.rsplit(".", 1)[-1].lower()
    if extension == "pdf":
        reader = PdfReader(io.BytesIO(content), strict=True)
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    if extension == "docx":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError("DOCX archive exceeds the extraction limit")
        document = WordDocument(io.BytesIO(content))
        return "\n".join(
            f"{'#' if paragraph.style.name.startswith('Heading') else ''} {paragraph.text}".strip()
            for paragraph in document.paragraphs
            if paragraph.text.strip()
        )
    if extension in {"txt", "md"}:
        return content.decode("utf-8")
    raise ValueError("Unsupported document format")


def clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[\t ]+", " ", text)
    text = re.sub(r"\n[ \t]+\n", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _paragraphs(text: str) -> Iterable[tuple[str | None, str]]:
    heading: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        value = line.strip()
        if not value:
            if body:
                yield heading, " ".join(body)
                body = []
            continue
        if value.startswith("#"):
            if body:
                yield heading, " ".join(body)
                body = []
            heading = value.lstrip("#").strip()[:512] or None
        else:
            body.append(value)
    if body:
        yield heading, " ".join(body)


def chunk_text(text: str, max_words: int = 300, overlap_words: int = 50) -> list[TextChunk]:
    if max_words <= 0 or overlap_words < 0 or overlap_words >= max_words:
        raise ValueError("Chunk sizes must satisfy 0 <= overlap < max_words")
    chunks: list[TextChunk] = []
    current_heading: str | None = None
    current: list[str] = []
    count = 0
    new_words = 0

    def emit(preserve_overlap: bool = True) -> None:
        nonlocal current, count, new_words
        if not current:
            return
        content = " ".join(current).strip()
        if content:
            chunks.append(TextChunk(index=len(chunks), heading=current_heading, content=content))
        carry = content.split()[-overlap_words:] if overlap_words and preserve_overlap else []
        current = [" ".join(carry)] if carry else []
        count = len(carry)
        new_words = 0

    for heading, paragraph in _paragraphs(text):
        if heading != current_heading and current:
            emit(preserve_overlap=False)
        if heading:
            current_heading = heading
        words = paragraph.split()
        offset = 0
        while offset < len(words):
            available = max_words - count
            if available <= 0:
                emit()
                available = max_words - count
            take = min(available, len(words) - offset)
            current.append(" ".join(words[offset : offset + take]))
            count += take
            new_words += take
            offset += take
            if count >= max_words:
                emit()
    if current and new_words:
        content = " ".join(current).strip()
        if content:
            chunks.append(TextChunk(index=len(chunks), heading=current_heading, content=content))
    return chunks


def embed_texts(texts: list[str], model_name: str, batch_size: int) -> list[list[float]]:
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise RuntimeError("Install the fastembed dependency to process documents") from exc
    model = TextEmbedding(model_name=model_name)
    vectors: list[list[float]] = []
    for offset in range(0, len(texts), batch_size):
        batch = texts[offset : offset + batch_size]
        vectors.extend(vector.tolist() for vector in model.embed(batch))
    if len(vectors) != len(texts):
        raise RuntimeError("Embedding model returned an unexpected number of vectors")
    return vectors
