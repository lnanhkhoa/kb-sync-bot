"""Delta-sync behaviour of `knowledge_base.sync` against an in-memory File Search store."""

import itertools
import threading
from types import SimpleNamespace

import pytest
from google.genai import types

from optibot.chunking import Article, chunk_article
from optibot.knowledge_base import sync

STORE = "fileSearchStores/test"


class FakeDocuments:
    def __init__(self, store: "FakeStore"):
        self._store = store

    def list(self, parent, config=None):
        assert parent == STORE
        return list(self._store.docs.values())

    def delete(self, name, config=None):
        with self._store.lock:
            if name not in self._store.docs:
                raise KeyError(name)
            del self._store.docs[name]
            self._store.deleted.append(name)


class FakeStore:
    """Just enough of `genai.Client` for `sync`: upload, list, delete."""

    def __init__(self, fail_slugs: set[str] = frozenset()):
        self.docs: dict[str, types.Document] = {}
        self.uploaded: list[str] = []
        self.deleted: list[str] = []
        self.fail_slugs = set(fail_slugs)
        self.lock = threading.Lock()
        self._ids = itertools.count()
        self.file_search_stores = SimpleNamespace(
            upload_to_file_search_store=self._upload, documents=FakeDocuments(self)
        )
        self.operations = SimpleNamespace(get=lambda op: op)

    def _upload(self, file_search_store_name, file, config):
        assert file_search_store_name == STORE
        display_name = config["display_name"]
        if display_name.split(" [")[0] in self.fail_slugs:
            return SimpleNamespace(done=True, error={"message": "quota exceeded"}, response=None)
        with self.lock:
            name = f"{STORE}/documents/doc-{next(self._ids)}"
            self.docs[name] = types.Document(
                name=name,
                display_name=display_name,
                custom_metadata=[types.CustomMetadata(**item) for item in config["custom_metadata"]],
            )
            self.uploaded.append(name)
        return SimpleNamespace(done=True, error=None, response=SimpleNamespace(document_name=name))

    def hashes(self, article_id: int) -> list[str]:
        """content_hash of every stored chunk of one article."""
        result = []
        for doc in self.docs.values():
            meta = {m.key: m.string_value for m in doc.custom_metadata}
            if meta["article_id"] == str(article_id):
                result.append(meta["content_hash"])
        return result


def article(article_id: int, content_hash: str = "v1", sections: int = 1) -> Article:
    # Each section is ~300 words, so every section becomes its own chunk.
    body = "\n\n".join(f"## Part {i}\n\n" + " ".join(["word"] * 300) for i in range(sections))
    return Article(article_id, f"Article {article_id}", f"https://help/{article_id}", f"article-{article_id}", body,
                   content_hash)


def run(store: FakeStore, articles, prune: bool = False):
    return sync(store, STORE, articles, prune=prune, workers=4)


def test_first_sync_uploads_every_chunk_tagged_with_its_article():
    store = FakeStore()
    report = run(store, [article(1, sections=2), article(2)])

    assert sorted(report.added) == [1, 2]
    assert report.chunks_uploaded == 3 == len(store.docs)
    assert store.hashes(1) == ["v1", "v1"] and store.hashes(2) == ["v1"]


def test_unchanged_articles_are_skipped_without_touching_the_store():
    store = FakeStore()
    run(store, [article(1, sections=2), article(2)])
    store.uploaded.clear()

    report = run(store, [article(1, sections=2), article(2)])

    assert sorted(report.skipped) == [1, 2]
    assert (report.added, report.updated, report.chunks_uploaded) == ([], [], 0)
    assert store.uploaded == [] and store.deleted == []


def test_changed_article_is_replaced_and_its_old_chunks_deleted():
    store = FakeStore()
    run(store, [article(1, sections=2), article(2)])
    old_docs = set(store.docs)

    report = run(store, [article(1, "v2", sections=3), article(2)])

    assert (report.updated, report.skipped) == ([1], [2])
    assert report.chunks_uploaded == 3 and report.chunks_deleted == 2
    assert store.hashes(1) == ["v2"] * 3
    assert old_docs - set(store.docs) == set(store.deleted)  # only article 1's old chunks went away


def test_new_article_is_added_alongside_existing_ones():
    store = FakeStore()
    run(store, [article(1)])

    report = run(store, [article(1), article(3)])

    assert (report.added, report.skipped) == ([3], [1])


def test_prune_removes_articles_that_are_no_longer_scraped():
    store = FakeStore()
    run(store, [article(1), article(2, sections=2)])

    kept = run(store, [article(1)])
    assert kept.removed == [] and store.hashes(2) == ["v1", "v1"]

    pruned = run(store, [article(1)], prune=True)
    assert pruned.removed == [2] and pruned.chunks_deleted == 2
    assert store.hashes(2) == [] and store.hashes(1) == ["v1"]


def test_failed_upload_keeps_the_previous_version_and_is_retried_next_run():
    store = FakeStore()
    run(store, [article(1)])

    store.fail_slugs = {"article-1"}
    failed = run(store, [article(1, "v2")])
    assert failed.failed == [1] and failed.updated == []
    assert store.hashes(1) == ["v1"]  # still answerable from the old version

    store.fail_slugs = set()
    retried = run(store, [article(1, "v2")])
    assert retried.updated == [1] and store.hashes(1) == ["v2"]


@pytest.mark.parametrize("leftover", ["v1", "v2"])
def test_leftover_chunks_from_an_interrupted_run_are_cleaned_up(leftover):
    """A crash between upload and delete leaves extra chunks; the next run must converge."""
    store = FakeStore()
    run(store, [article(1, "v2")])
    stray = article(1, leftover)
    store._upload(STORE, None, {
        "display_name": "article-1 [1/1]",
        "custom_metadata": [{"key": "article_id", "string_value": "1"},
                            {"key": "content_hash", "string_value": stray.content_hash}],
    })

    report = run(store, [article(1, "v2")])

    assert report.updated == [1]
    assert store.hashes(1) == ["v2"] * len(chunk_article(article(1, "v2")))
    assert run(store, [article(1, "v2")]).skipped == [1]
