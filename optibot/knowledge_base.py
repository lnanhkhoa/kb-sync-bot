"""Keep a Gemini File Search store in sync with the scraped articles.

Each chunk from `optibot.chunking` is uploaded as its own store document tagged
with `article_id` and `content_hash`. The store itself is therefore the sync
state: re-running uploads only articles whose hash changed, and needs no local
database (which matters for a stateless daily container).
"""

from __future__ import annotations

import io
import logging
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from optibot.chunking import GEMINI_MAX_WORDS, Article, chunk_article

log = logging.getLogger(__name__)

DEFAULT_STORE_DISPLAY_NAME = "optibot-kb"
UPLOAD_TIMEOUT_S = 300
# Each uploaded chunk is <= GEMINI_MAX_WORDS, so Gemini never re-splits it.
CHUNKING = {"white_space_config": {"max_tokens_per_chunk": GEMINI_MAX_WORDS, "max_overlap_tokens": 0}}


@dataclass
class SyncReport:
    added: list[int] = field(default_factory=list)
    updated: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    chunks_uploaded: int = 0
    chunks_deleted: int = 0

    def summary(self) -> str:
        files = len(self.added) + len(self.updated)
        return (
            f"embedded {self.chunks_uploaded} chunks from {files} files | "
            f"added={len(self.added)} updated={len(self.updated)} skipped={len(self.skipped)} "
            f"removed={len(self.removed)} failed={len(self.failed)} chunks_deleted={self.chunks_deleted}"
        )


def make_client(api_key: str) -> genai.Client:
    retry = types.HttpRetryOptions(attempts=5, initial_delay=2, max_delay=60, http_status_codes=[429, 500, 502, 503, 504])
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(retry_options=retry))


def get_or_create_store(client: genai.Client, display_name: str = DEFAULT_STORE_DISPLAY_NAME) -> str:
    """Resolve the store by display name so the job needs no stored id."""
    for store in client.file_search_stores.list():
        if store.display_name == display_name:
            return store.name
    store = client.file_search_stores.create(config={"display_name": display_name})
    log.info("created file search store %s", store.name)
    return store.name


def sync(
    client: genai.Client,
    store_name: str,
    articles: Iterable[Article],
    *,
    url_by_file: Mapping[str, str] | None = None,
    prune: bool = False,
    workers: int = 16,
) -> SyncReport:
    """Upload new/changed articles, skip unchanged ones, optionally delete vanished ones.

    `url_by_file` resolves cross-article links (defaults to the synced articles only).
    New chunks are uploaded before old ones are deleted, so a crash mid-run never
    leaves an article missing; the next run sees mixed hashes and redoes it.
    """
    articles = list(articles)
    if url_by_file is None:
        url_by_file = {f"{a.slug}.md": a.url for a in articles}
    existing = _documents_by_article(client, store_name)
    report = SyncReport()

    uploads: dict[int, list[str]] = {}
    for article in articles:
        chunks = chunk_article(article, url_by_file)
        docs = existing.get(article.id, [])
        if docs and len(docs) == len(chunks) and all(_meta(d, "content_hash") == article.content_hash for d in docs):
            report.skipped.append(article.id)
        else:
            uploads[article.id] = chunks

    by_id = {a.id: a for a in articles}
    with ThreadPoolExecutor(workers) as pool:
        futures = {
            article_id: [
                pool.submit(_upload_chunk, client, store_name, by_id[article_id], index, len(chunks), text)
                for index, text in enumerate(chunks)
            ]
            for article_id, chunks in uploads.items()
        }
        stale: list[str] = []
        for article_id, chunk_futures in futures.items():
            errors = [f.exception() for f in chunk_futures if f.exception()]
            if errors:
                log.error("article %s: %d/%d chunks failed: %s", article_id, len(errors), len(chunk_futures), errors[0])
                report.failed.append(article_id)
                continue  # keep the previous version (if any) searchable
            report.chunks_uploaded += len(chunk_futures)
            (report.updated if article_id in existing else report.added).append(article_id)
            stale += [d.name for d in existing.get(article_id, [])]

        if prune:
            current = {a.id for a in articles}
            for article_id, docs in existing.items():
                if article_id not in current:
                    report.removed.append(article_id)
                    stale += [d.name for d in docs]

        delete = client.file_search_stores.documents.delete
        deletes = [pool.submit(delete, name=name, config={"force": True}) for name in stale]
        for name, future in zip(stale, deletes):
            if future.exception():
                log.warning("could not delete stale document %s: %s", name, future.exception())
            else:
                report.chunks_deleted += 1
    return report


def _upload_chunk(client: genai.Client, store_name: str, article: Article, index: int, total: int, text: str) -> str:
    op = client.file_search_stores.upload_to_file_search_store(
        file_search_store_name=store_name,
        file=io.BytesIO(text.encode("utf-8")),
        config={
            "display_name": f"{article.slug} [{index + 1}/{total}]",
            "mime_type": "text/markdown",
            "chunking_config": CHUNKING,
            "custom_metadata": [
                {"key": "article_id", "string_value": str(article.id)},
                {"key": "content_hash", "string_value": article.content_hash},
                {"key": "title", "string_value": article.title},
                {"key": "url", "string_value": article.url},
                {"key": "chunk", "numeric_value": index},
            ],
        },
    )
    deadline = time.monotonic() + UPLOAD_TIMEOUT_S
    while not op.done:
        if time.monotonic() > deadline:
            raise TimeoutError(f"upload of {article.slug} chunk {index} still running after {UPLOAD_TIMEOUT_S}s")
        time.sleep(1)
        op = client.operations.get(op)
    if op.error:
        raise RuntimeError(f"upload of {article.slug} chunk {index} failed: {op.error}")
    return op.response.document_name


def _documents_by_article(client: genai.Client, store_name: str) -> dict[int, list[types.Document]]:
    docs: dict[int, list[types.Document]] = defaultdict(list)
    for doc in client.file_search_stores.documents.list(parent=store_name, config={"page_size": 20}):
        article_id = _meta(doc, "article_id")
        if article_id is not None:
            docs[int(article_id)].append(doc)
    return docs


def _meta(doc: types.Document, key: str) -> str | None:
    for item in doc.custom_metadata or []:
        if item.key == key:
            return item.string_value
    return None
