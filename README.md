# OptiBot mini-clone

## Setup

```bash
uv sync                       # Python ≥ 3.11
cp .env.sample .env           # set GEMINI_API_KEY (Google AI Studio key)
```

`make help` lists shortcuts for the commands below (`setup`, `test`, `scrape`, `upload`, `ask Q="…"`, `job`,
`docker-build`, `docker-run`).

## 1. Scrape ⇒ Markdown

```bash
uv run python -m optibot.scrape                 # 40 articles -> articles/: the pinned YouTube how-to + 39 most recently updated
uv run python -m optibot.scrape --limit 30 --include how-to-use-youtube-with-optisigns --out /tmp/articles
uv run python -m optibot.scrape --limit 0       # every published en-us article (396 today)
uv run pytest                                   # converter tests
```

Source: the public Zendesk Help Center API (`/api/v2/help_center/en-us/articles.json`, sorted by
`updated_at` desc, cursor pagination, 100/page, retry on 429/5xx). The API returns only the article body,
so site nav, header, footer, and related-article widgets are never fetched.

Only a subset is scraped to keep the knowledge base small: the `--include` articles plus the most recently
updated ones, `--limit` in total (default 40). Pages are read newest first and fetching stops as soon as the
quota is filled and every pinned article is found, so a default run reads 1 page. Picking by recency means
new or edited articles always enter the knowledge base. The YouTube article is pinned because the
sanity-check question needs it. Files in `articles/` that are no longer selected are deleted.

Each article becomes `articles/<slug>.md`, where the slug comes from the title. If two titles produce the
same slug, the article id is appended to keep names unique. Each file has:

- YAML front matter: `id`, `title`, `url`, `section_id`, `labels`, `created_at`, `updated_at`.
- `# Title` and an `Article URL: …` line, which is the line the assistant cites.

Cleaning rules (`optibot/markdown.py`):

| Source HTML | Markdown |
| --- | --- |
| `<script>/<style>`, comments, `span`/`font`/`u` wrappers, inline styles | dropped (text kept) |
| `<a name="Foo">` + TOC `href="#Foo"` | TOC link rewritten to the GitHub id of the heading it marks (case and `&amp;amp;` tolerant) |
| link to another scraped article | relative `./<slug>.md#fragment` |
| other relative link / image | absolute `https://support.optisigns.com/...` |
| `<pre><code class="language-x">` (Prism spans, `<br>` lines) | fenced block with language, line breaks preserved |
| YouTube `<iframe>`, `<video>` | `[YouTube video](https://www.youtube.com/watch?v=…)` / `[Video: title](src)` |
| one-column "NOTE" tables | blockquote; real tables stay GFM tables |
| `**` inside headings, empty bold, dangling `<br>` | removed |

Across all 396 articles, out of 1,374 in-page anchor links, the 9 that still don't resolve point to targets
missing from the source articles themselves.

## 2. Assistant + vector store (Google Gemini File Search)

```bash
# sync articles/ -> File Search store "optibot-kb"; --prune deletes store articles no longer scraped
uv run python -m optibot.upload --prune
uv run python -m optibot.assistant "How do I add a YouTube video?"
```

We use Gemini because OpenAI shut down the Assistants API on 2026-08-26. The store is found by its display
name and created on first run, so no store id needs to be saved anywhere. The system prompt is in
`optibot/assistant.py` and is word-for-word the assignment text.

The upload takes every file in `articles/`; which articles those are is decided by the scraper (section 1).

**Chunking** (`optibot/chunking.py`): chunks are built on our side and follow the article's headings.
- Text is split into blocks at blank lines. A fenced code block always stays one block.
- Blocks are packed into chunks of up to 450 words.
- A heading starts a new chunk once the current chunk has at least 120 words. Smaller sections are
  merged with the one before them.
- A single block over the budget is split by line and then by word. Code pieces get their fences re-added.
- Every chunk starts with `# Title`, `Article URL: …` and `Section: H2 > H3`. Whichever chunk the retriever
  returns, the model can still cite its article.
- No overlap is needed because each chunk carries its section header.
- Links between scraped articles become live help-center URLs.

Gemini's whitespace chunker splits at 512 words, so it never re-splits our chunks. That makes
1 uploaded document = 1 embedded chunk, and the logged chunk count is exact. Each document carries
`article_id`, `content_hash`, `title`, `url` and `chunk` metadata, which the sync uses as its state:
- **skipped:** the stored hashes and chunk count already match the local article.
- **added / updated:** otherwise, the article's new chunks are uploaded first and its old chunks are
  deleted afterwards, so a failure never leaves an article missing.
- **removed:** with `--prune`, store articles that no longer exist locally are deleted.

The log line shows the counts, for example
`embedded 17 chunks from 3 files | added=3 updated=0 skipped=0 removed=0 failed=0`.
