"""Scrape support.optisigns.com articles into `<slug>.md` files.

Only a subset is fetched: the `--include` slugs plus the most recently updated articles, `--limit` in total.
Usage: uv run python -m optibot.scrape [--out articles] [--limit 40] [--include SLUG ...]
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from optibot.markdown import article_to_markdown, slugify
from optibot.zendesk import DEFAULT_BASE_URL, iter_articles

log = logging.getLogger(__name__)

DEFAULT_LIMIT = 40
# Pinned so the knowledge base can always answer the sanity-check question.
DEFAULT_INCLUDE = ("how-to-use-youtube-with-optisigns",)


def assign_filenames(articles: Iterable[Mapping[str, Any]]) -> dict[int, str]:
    """Map article id -> `<slug>.md`; colliding titles get the article id appended."""
    by_slug: dict[str, list[int]] = {}
    for article in articles:
        slug = slugify(article["title"]) or str(article["id"])
        by_slug.setdefault(slug, []).append(article["id"])
    names: dict[int, str] = {}
    for slug, ids in by_slug.items():
        for article_id in ids:
            names[article_id] = f"{slug}.md" if len(ids) == 1 else f"{slug}-{article_id}.md"
    return names


def select_articles(
    articles: Iterator[Mapping[str, Any]], limit: int | None, include: Iterable[str]
) -> list[Mapping[str, Any]]:
    """Pick the `include` slugs plus the first other articles, `limit` in total (`None` = all).

    Stops consuming `articles` once the quota is met and every pinned slug is found, so with a
    newest-first stream only the pages that are needed get fetched.
    """
    if limit is None:
        return list(articles)
    missing = set(include)
    quota = max(limit - len(missing), 0)
    pinned: list[Mapping[str, Any]] = []
    recent: list[Mapping[str, Any]] = []
    for article in articles:
        slug = slugify(article["title"])
        if slug in missing:
            missing.discard(slug)
            pinned.append(article)
        elif len(recent) < quota:
            recent.append(article)
        if not missing and len(recent) >= quota:
            break
    if missing:
        raise SystemExit(f"--include: no article named {sorted(missing)}")
    return pinned + recent


def scrape(
    out_dir: Path,
    base_url: str = DEFAULT_BASE_URL,
    locale: str = "en-us",
    limit: int | None = DEFAULT_LIMIT,
    include: Iterable[str] = DEFAULT_INCLUDE,
) -> list[Path]:
    """Write the selected articles to `out_dir` and delete every other `.md` file there."""
    articles = select_articles(iter_articles(base_url, locale), limit, include)
    # Only scraped articles are link targets, so cross-links never point at missing files.
    filenames = assign_filenames(articles)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for article in articles:
        path = out_dir / filenames[article["id"]]
        path.write_text(article_to_markdown(article, filenames, base_url), encoding="utf-8")
        written.append(path)
    # Articles deleted upstream, renamed, or no longer selected must not linger and get re-uploaded.
    stale = set(out_dir.glob("*.md")) - set(written)
    for path in stale:
        path.unlink()
    log.info("wrote %d articles to %s (removed %d stale files)", len(written), out_dir, len(stale))
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("articles"), help="output directory (default: articles)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--locale", default="en-us")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"articles to scrape, --include ones first (default {DEFAULT_LIMIT}; 0 = all)")
    parser.add_argument("--include", action="append", metavar="SLUG",
                        help=f"always scrape this article (default: {', '.join(DEFAULT_INCLUDE)})")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    scrape(args.out, args.base_url, args.locale, args.limit or None, args.include or DEFAULT_INCLUDE)


if __name__ == "__main__":
    main()
