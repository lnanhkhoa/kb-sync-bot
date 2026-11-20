"""Split scraped article Markdown into self-contained, heading-aware chunks.

Every chunk repeats the article title and its `Article URL:` line, so whatever
chunk the retriever returns, the model can cite the article it came from.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Gemini's white-space chunker caps a chunk at 512 whitespace-separated words.
# Staying under it means Gemini keeps each uploaded chunk whole (1 document = 1 chunk),
# so the chunk count we log is exact rather than an estimate.
GEMINI_MAX_WORDS = 512
MAX_WORDS = 450  # body + title/URL header; the rest of the headroom is for the "Section:" line
MAX_SECTION_WORDS = GEMINI_MAX_WORDS - MAX_WORDS - 2
MIN_WORDS = 120  # below this, a new heading is merged into the current chunk instead of starting one
# Bump when the chunking rules change so the next sync re-uploads every article.
CHUNKER_VERSION = "1"
HEADING = re.compile(r"^(#{1,6}) +(.+)$")
FENCE = re.compile(r"^\s*(`{3,})")
RELATIVE_ARTICLE_LINK = re.compile(r"\]\(\./([^)#\s]+\.md)(#[^)\s]*)?\)")


@dataclass(frozen=True)
class Article:
    id: int
    title: str
    url: str
    slug: str
    body: str
    content_hash: str
    updated_at: str = ""


def load_article(path: Path) -> Article:
    """Parse a file written by `optibot.scrape` (JSON-valued front matter + Markdown)."""
    text = path.read_text(encoding="utf-8")
    _, front, rest = text.split("---\n", 2)
    meta = {key: json.loads(value) for key, value in (line.split(": ", 1) for line in front.splitlines())}
    # Drop the "# Title" / "Article URL:" preamble; every chunk header re-adds it.
    body = re.sub(r"\A\s*# .*\n+Article URL: .*\n", "", rest)
    digest = hashlib.sha256(f"{CHUNKER_VERSION}\n{text}".encode()).hexdigest()
    return Article(meta["id"], meta["title"], meta["url"], path.stem, body.strip(), digest, meta.get("updated_at") or "")


def chunk_article(article: Article, url_by_file: Mapping[str, str] | None = None) -> list[str]:
    """Pack whole sections into chunks of at most MAX_WORDS, splitting only oversized blocks.

    `url_by_file` maps scraped filenames to article URLs: the knowledge base has no
    sibling `.md` files, so cross-article links must point at the live help center.
    """
    header = f"# {article.title}\nArticle URL: {article.url}\n"
    budget = MAX_WORDS - _words(header)
    body = article.body
    if url_by_file:
        def to_url(match: re.Match[str]) -> str:
            url = url_by_file.get(match.group(1))
            return f"]({url}{match.group(2) or ''})" if url else match.group(0)

        body = RELATIVE_ARTICLE_LINK.sub(to_url, body)

    chunks: list[str] = []
    parts: list[str] = []
    used = 0
    section: list[tuple[int, str]] = []  # heading path, e.g. [(2, "Setup"), (3, "Android")]
    chunk_section = ""

    def flush() -> None:
        nonlocal parts, used
        if parts:
            section_line = f"Section: {_truncate(chunk_section, MAX_SECTION_WORDS)}\n" if chunk_section else ""
            chunks.append(f"{header}{section_line}\n" + "\n\n".join(parts) + "\n")
        parts, used = [], 0

    for block in _blocks(body):
        heading = HEADING.match(block)
        if heading and "\n" not in block:
            level = len(heading.group(1))
            section = [(lvl, txt) for lvl, txt in section if lvl < level] + [(level, heading.group(2).strip())]
            if used >= MIN_WORDS:
                flush()
        for piece in _split_oversized(block, budget):
            size = _words(piece)
            if used + size > budget:
                flush()
            if not parts:
                chunk_section = " > ".join(txt for _, txt in section)
            parts.append(piece)
            used += size
    flush()
    return chunks


def _blocks(markdown: str) -> list[str]:
    """Blank-line separated blocks; a fenced code block is always one block."""
    blocks: list[str] = []
    current: list[str] = []
    fence: str | None = None
    for line in markdown.splitlines():
        marker = FENCE.match(line)
        if fence:
            current.append(line)
            if marker and marker.group(1).startswith(fence):
                fence = None
            continue
        if marker:
            fence = marker.group(1)
            current.append(line)
        elif line.strip():
            if HEADING.match(line) and current:  # a heading always starts its own block
                blocks.append("\n".join(current))
                current = []
            current.append(line)
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def _split_oversized(block: str, budget: int) -> list[str]:
    if _words(block) <= budget:
        return [block]
    lines = block.splitlines()
    open_fence = close_fence = ""
    if FENCE.match(lines[0]) and len(lines) > 1 and FENCE.match(lines[-1]):
        # Re-fence every piece of a long code block so each chunk stays valid Markdown.
        open_fence, close_fence, lines = lines[0], lines[-1], lines[1:-1]
        budget -= _words(open_fence) + _words(close_fence)
    pieces: list[list[str]] = [[]]
    used = 0
    for line in lines:
        for segment in _split_words(line, budget):
            size = _words(segment)
            if used + size > budget and pieces[-1]:
                pieces.append([])
                used = 0
            pieces[-1].append(segment)
            used += size
    if open_fence:
        return ["\n".join([open_fence, *piece, close_fence]) for piece in pieces]
    return ["\n".join(piece) for piece in pieces]


def _split_words(line: str, budget: int) -> list[str]:
    words = line.split()
    if len(words) <= budget:
        return [line]
    return [" ".join(words[i : i + budget]) for i in range(0, len(words), budget)]


def _truncate(text: str, max_words: int) -> str:
    words = text.split()
    return text if len(words) <= max_words else " ".join(words[:max_words]) + " …"


def _words(text: str) -> int:
    return len(text.split())
