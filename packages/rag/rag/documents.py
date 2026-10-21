"""Load documents into a common shape: a list of sections, each with a heading path and text.

Two sources:
- Markdown files written for the fictional Company M (front matter + `#` headings, tables kept intact).
- Public PDFs (FDA guidance, 510(k) summaries) parsed with pdfplumber. Docling is the planned
  alternative backend; it needs models from Hugging Face, so it runs on the local machine.

Every document carries access metadata (`group`, `classification`) that retrieval filters on.
Emails and phone numbers are masked at ingestion so personal contact details never enter the index.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Section:
    heading: str            # heading path, e.g. "II. Background > A. Scope"
    text: str
    page: int | None = None  # first page of the section (PDF only)
    is_table: bool = False


@dataclass
class Document:
    doc_id: str
    title: str
    group: str              # access group: public / internal / proj-a / proj-b
    classification: str     # public / internal / confidential
    source: str             # file path or URL
    lang: str
    sections: list[Section] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(s.text for s in self.sections)


# ---------- PII masking ----------

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?:\+\d{1,3}[\s-]?)?\(?\d{2,4}\)?[\s-]\d{3,4}[\s-]\d{3,4}(?:\s*(?:ext\.?|x)\s*\d+)?", re.I)


def mask_pii(text: str) -> tuple[str, int]:
    """Replace emails and phone numbers; return the masked text and the number of replacements."""
    text, n1 = EMAIL.subn("[EMAIL]", text)
    text, n2 = PHONE.subn("[PHONE]", text)
    return text, n1 + n2


# ---------- Markdown (synthetic internal documents) ----------

def parse_front_matter(raw: str) -> tuple[dict, str]:
    if not raw.startswith("---\n"):
        raise ValueError("missing front matter")
    end = raw.index("\n---\n", 4)
    meta = {}
    for line in raw[4:end].splitlines():
        if line.strip():
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, raw[end + 5:]


def load_markdown(path: Path) -> Document:
    meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
    doc = Document(meta["doc_id"], meta["title"], meta["group"], meta["classification"], str(path),
                   meta.get("lang", "zh"))
    stack: list[tuple[int, str]] = []
    buf: list[str] = []

    def flush():
        """Emit the lines under the current heading: prose runs and tables become separate sections."""
        heading = " > ".join(h for _, h in stack) or doc.title
        runs: list[tuple[bool, list[str]]] = []
        for line in buf:
            is_row = line.lstrip().startswith("|")
            if not line.strip():
                if runs and not runs[-1][0]:
                    runs[-1][1].append("")  # keep paragraph breaks inside prose
                continue
            if runs and runs[-1][0] == is_row:
                runs[-1][1].append(line)
            else:
                runs.append((is_row, [line]))
        for is_table, lines in runs:
            text = "\n".join(lines).strip()
            if text:
                doc.sections.append(Section(heading, text, is_table=is_table))
        buf.clear()

    for line in body.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            flush()
            level = len(m.group(1))
            stack = [(lv, h) for lv, h in stack if lv < level] + [(level, m.group(2).strip())]
        else:
            buf.append(line)
    flush()
    return doc


# ---------- PDF (public documents) ----------

BOILERPLATE = re.compile(r"^(Contains Nonbinding Recommendations|Draft\s*[–-]\s*Not for Implementation)\s*$", re.I)
DOT_LEADER = re.compile(r"\.{5,}|(?:\s\.){5,}")
ROMAN = r"(?:I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV)"
HEADINGS = {  # name -> (level, pattern)
    "roman": (1, re.compile(rf"^{ROMAN}\.\s+[A-Z][^.]{{2,100}}$")),
    "appendix": (1, re.compile(r"^Appendix\s+[A-Z0-9]+[.:]\s+[A-Z].{0,90}$")),
    "letter": (2, re.compile(r"^[A-H]\.\s+[A-Z][^.]{2,100}$")),
    "numbered": (3, re.compile(r"^\d{1,2}\.\s+[A-Z][A-Za-z0-9 ()/&,'’?:-]{2,90}$")),
}
HEADING_STYLES = {  # which heading patterns to trust for each kind of PDF
    "fda_guidance": ("roman", "appendix", "letter", "numbered"),
    "510k_decision": ("numbered",),  # roman and letter lines in 510(k) summaries are list items, not headings
}
CONNECTORS = {"of", "and", "or", "to", "for", "the", "a", "an", "with", "when", "new", "in", "on", "by"}


def _strip_line_numbers(lines: list[str]) -> list[str]:
    """Draft guidances print a line number in front of every line; detect that and remove it."""
    numbered = sum(bool(re.match(r"^\d{1,4}(\s|$)", ln)) for ln in lines)
    if numbered < 0.4 * max(len(lines), 1):
        return lines
    out = []
    for ln in lines:
        if re.fullmatch(r"\d{1,4}", ln.strip()):
            continue
        out.append(re.sub(r"^\d{1,4}\s+", "", ln))
    return out


def _is_toc_page(lines: list[str]) -> bool:
    return any(ln.strip().lower() == "table of contents" for ln in lines) or \
        sum(bool(DOT_LEADER.search(ln)) for ln in lines) >= 5


def _heading_level(line: str, styles: tuple[str, ...]) -> int | None:
    if len(line.split()) > 16:
        return None
    for name in styles:
        level, pat = HEADINGS[name]
        if pat.match(line):
            return level
    return None


def _continues_heading(heading: str, nxt: str, styles) -> bool:
    """A heading wrapped onto the next line: the next line is short and clearly a continuation."""
    if not nxt or len(nxt.split()) > 12 or nxt.endswith(".") or _heading_level(nxt, styles) is not None:
        return False
    last = heading.split()[-1].lower()
    return heading.endswith(("-", ",")) or last in CONNECTORS or nxt[0].islower() or nxt[0].isdigit()


def load_pdf(path: Path, doc_id: str, title: str, kind: str = "fda_guidance", group: str = "public",
             classification: str = "public", source: str | None = None) -> tuple[Document, int]:
    import pdfplumber  # optional dependency: only needed for PDFs

    styles = HEADING_STYLES[kind]
    doc = Document(doc_id, title, group, classification, source or str(path), "en")
    lines: list[tuple[int, str]] = []
    masked = 0
    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            raw = [ln.rstrip() for ln in (page.extract_text() or "").splitlines()]
            raw = [ln.strip() for ln in _strip_line_numbers(raw) if ln.strip() and not BOILERPLATE.match(ln.strip())]
            if _is_toc_page(raw):
                continue
            for ln in raw:
                ln, n = mask_pii(ln)
                masked += n
                lines.append((pno, ln))

    stack: list[tuple[int, str]] = []
    buf: list[str] = []
    buf_page = 1

    def flush():
        nonlocal buf
        text = re.sub(r"[ \t]+", " ", "\n".join(buf)).strip()
        if text:
            doc.sections.append(Section(" > ".join(h for _, h in stack) or title, text, page=buf_page))
        buf = []

    i = 0
    while i < len(lines):
        pno, ln = lines[i]
        level = _heading_level(ln, styles)
        if level is not None:
            flush()
            heading = ln
            for _ in range(2):
                if i + 1 < len(lines) and _continues_heading(heading, lines[i + 1][1], styles):
                    i += 1
                    sep = "" if heading.endswith("-") else " "
                    heading = heading + sep + lines[i][1]
                else:
                    break
            stack = [(lv, h) for lv, h in stack if lv < level] + [(level, heading.rstrip(":"))]
            buf_page = pno
        else:
            if not buf:
                buf_page = pno
            buf.append(ln)
        i += 1
    flush()
    return doc, masked


# ---------- Corpus ----------

def load_corpus(corpus_dir: Path, raw_dir: Path, include_public: bool = True) -> tuple[list[Document], dict]:
    """Synthetic Markdown under corpus_dir/<group>/ plus public PDFs listed in corpus_dir/public_manifest.json."""
    docs = [load_markdown(p) for p in sorted(corpus_dir.glob("*/*.md"))]
    stats = {"markdown_docs": len(docs), "pdf_docs": 0, "pdf_missing": [], "pii_masked": 0}
    if not include_public:
        return docs, stats
    manifest = json.loads((corpus_dir / "public_manifest.json").read_text(encoding="utf-8"))
    for item in manifest["documents"]:
        path = raw_dir / item["file"]
        if not path.exists():
            stats["pdf_missing"].append(item["doc_id"])
            continue
        doc, masked = load_pdf(path, item["doc_id"], item["title"], kind=item["kind"], source=item["url"])
        docs.append(doc)
        stats["pdf_docs"] += 1
        stats["pii_masked"] += masked
    return docs, stats
