# Scrape ⇒ Markdown

```bash
uv run python -m optibot.scrape                 # 40 articles -> articles/: the pinned YouTube how-to + 39 most recently updated
uv run python -m optibot.scrape --limit 30 --include how-to-use-youtube-with-optisigns --out /tmp/articles
uv run python -m optibot.scrape --limit 0       # every published en-us article (396 today)
```

## Source

Articles come from the public Zendesk Help Center API (`/api/v2/help_center/en-us/articles.json`), sorted by
`updated_at` desc, with cursor pagination at 100 per page and retries on 429/5xx. The API returns only the
article body, so site nav, header, footer, and related-article widgets are never fetched.

## Selection

Only a subset is scraped, to keep the knowledge base small: the `--include` articles plus the most recently
updated ones, `--limit` in total (default 40). Pages are read newest first, and fetching stops as soon as the
quota is filled and every pinned article is found, so a default run reads 1 page.

Picking by recency means new or edited articles always enter the knowledge base. The YouTube article is
pinned because the sanity-check question needs it. Files in `articles/` that are no longer selected are
deleted.

## Output

Each article becomes `articles/<slug>.md`, where the slug comes from the title. If two titles produce the
same slug, the article id is appended to keep names unique. Each file has:

- YAML front matter: `id`, `title`, `url`, `section_id`, `labels`, `created_at`, `updated_at`.
- `# Title` and an `Article URL: …` line, which is the line the assistant cites.

## Cleaning rules (`optibot/markdown.py`)

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

Across all 396 articles there are 1,374 in-page anchor links. The 9 that still don't resolve point to
targets that are missing from the source articles themselves.
