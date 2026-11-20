# Tests

```bash
uv run pytest        # or: make test — 20 tests, ~0.3s, no network or API key needed
```

| File | Covers |
| --- | --- |
| `tests/test_markdown.py` | HTML → Markdown: front matter and the `Article URL:` line, TOC anchors, relative and absolute links, code fences, media links, callout tables, slug collisions |
| `tests/test_chunking.py` | chunks stay ≤ 512 words and keep the title/URL/section header; split code is re-fenced; cross-article links are rewritten; the content hash changes with the file |
| `tests/test_sync.py` | delta sync against an in-memory store: added / updated / skipped / removed (`--prune`); a failed upload keeps the old version and is retried next run; leftover chunks from an interrupted run are cleaned up |
