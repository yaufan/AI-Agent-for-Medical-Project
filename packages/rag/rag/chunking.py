"""Two chunking strategies, so the effect of structure can be measured instead of assumed.

- `structured`: follow the document's headings; split long sections at paragraph or sentence
  boundaries; never cut a table in the middle of a row, and repeat its header row when a table
  has to be split; prefix every chunk with its heading path so the heading words are searchable.
- `fixed`: a sliding window over the whole document text, ignoring structure (the usual baseline).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .documents import Document


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    group: str
    classification: str
    heading: str
    text: str           # what is indexed and shown to the LLM
    page: int | None
    is_table: bool


SENTENCE_END = re.compile(r"(?<=[.!?。！？；;])\s+|\n\s*\n")


def _split_prose(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    pieces = [p for p in SENTENCE_END.split(text) if p and p.strip()]
    out, cur = [], ""
    for p in pieces:
        p = p.strip()
        if cur and len(cur) + 1 + len(p) > max_chars:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip() if cur else p
        while len(cur) > max_chars:  # a single very long sentence
            out.append(cur[:max_chars])
            cur = cur[max_chars:]
    if cur:
        out.append(cur)
    return out


def _split_table(text: str, max_chars: int) -> list[str]:
    rows = text.splitlines()
    if len(text) <= max_chars or len(rows) <= 3:
        return [text]
    header = rows[:2]  # header row + separator row
    out, cur = [], list(header)
    for row in rows[2:]:
        if len("\n".join(cur + [row])) > max_chars and len(cur) > 2:
            out.append("\n".join(cur))
            cur = list(header)
        cur.append(row)
    out.append("\n".join(cur))
    return out


def structured(doc: Document, max_chars: int = 1200) -> list[Chunk]:
    chunks: list[Chunk] = []
    for sec in doc.sections:
        parts = _split_table(sec.text, max_chars) if sec.is_table else _split_prose(sec.text, max_chars)
        for part in parts:
            n = len(chunks)
            chunks.append(Chunk(f"{doc.doc_id}#s{n:03d}", doc.doc_id, doc.group, doc.classification,
                                sec.heading, f"[{doc.title} | {sec.heading}]\n{part}", sec.page, sec.is_table))
    return chunks


def fixed(doc: Document, size: int = 1200, overlap: int = 200) -> list[Chunk]:
    text = re.sub(r"\s+", " ", doc.text)
    chunks, start = [], 0
    while start < len(text):
        n = len(chunks)
        chunks.append(Chunk(f"{doc.doc_id}#f{n:03d}", doc.doc_id, doc.group, doc.classification,
                            "", text[start:start + size], None, False))
        if start + size >= len(text):
            break
        start += size - overlap
    return chunks


STRATEGIES = {"structured": structured, "fixed": fixed}


def chunk_corpus(docs: list[Document], strategy: str = "structured", **kw) -> list[Chunk]:
    fn = STRATEGIES[strategy]
    return [c for d in docs for c in fn(d, **kw)]
