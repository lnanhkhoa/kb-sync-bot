"""Upload scraped Markdown articles to the Gemini File Search store.

Usage: uv run python -m optibot.upload [--dir articles] [--prune]
Env:   GEMINI_API_KEY (required), GEMINI_STORE_DISPLAY_NAME (default: optibot-kb)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from optibot.chunking import load_article
from optibot.knowledge_base import DEFAULT_STORE_DISPLAY_NAME, SyncReport, get_or_create_store, make_client, sync

log = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for noisy in ("httpx", "httpx2"):  # per-request INFO lines from the Gemini SDK
        logging.getLogger(noisy).setLevel(logging.WARNING)


def upload_dir(api_key: str, articles_dir: Path, *, prune: bool = False, workers: int = 16) -> SyncReport:
    """Sync every article in `articles_dir`; the scraper decides which articles are there."""
    articles = [load_article(path) for path in sorted(articles_dir.glob("*.md"))]
    client = make_client(api_key)
    store = get_or_create_store(client, os.environ.get("GEMINI_STORE_DISPLAY_NAME", DEFAULT_STORE_DISPLAY_NAME))
    log.info("syncing %d articles from %s into %s", len(articles), articles_dir, store)
    url_by_file = {f"{a.slug}.md": a.url for a in articles}
    report = sync(client, store, articles, url_by_file=url_by_file, prune=prune, workers=workers)
    log.info(report.summary())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=Path("articles"), help="scraped Markdown directory")
    parser.add_argument("--prune", action="store_true", help="delete store articles missing from --dir")
    parser.add_argument("--workers", type=int, default=16, help="parallel uploads")
    args = parser.parse_args()
    configure_logging()
    load_dotenv()
    report = upload_dir(os.environ["GEMINI_API_KEY"], args.dir, prune=args.prune, workers=args.workers)
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
