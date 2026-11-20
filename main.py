"""Daily job: re-scrape the help center, then upload only new/changed articles to the File Search store.

Run once and exit (0 = success, 1 = some articles failed to upload):
    python main.py
Env:
    GEMINI_API_KEY (or API_KEY)  required
    SCRAPE_LIMIT                 articles scraped and kept in the store (default 40; 0 = all)
    SCRAPE_INCLUDE               comma-separated slugs always scraped (default: the YouTube how-to)
    ARTICLES_DIR                 scrape output directory (default: articles)
    GEMINI_STORE_DISPLAY_NAME    File Search store name (default: optibot-kb)
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from optibot.scrape import DEFAULT_INCLUDE, DEFAULT_LIMIT, scrape
from optibot.upload import configure_logging, upload_dir

log = logging.getLogger("optibot.job")


def main() -> int:
    configure_logging()
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("API_KEY")
    if not api_key:
        log.error("set GEMINI_API_KEY (or API_KEY)")
        return 2
    limit = int(os.environ.get("SCRAPE_LIMIT", DEFAULT_LIMIT)) or None
    include = [s for s in os.environ.get("SCRAPE_INCLUDE", ",".join(DEFAULT_INCLUDE)).split(",") if s]
    articles_dir = Path(os.environ.get("ARTICLES_DIR", "articles"))

    started = time.monotonic()
    scraped = scrape(articles_dir, limit=limit, include=include)
    # The store mirrors articles/, so prune articles that are no longer scraped.
    report = upload_dir(api_key, articles_dir, prune=True)
    log.info(
        "run complete in %.0fs: scraped=%d added=%d updated=%d skipped=%d removed=%d failed=%d chunks_uploaded=%d",
        time.monotonic() - started, len(scraped), len(report.added), len(report.updated), len(report.skipped),
        len(report.removed), len(report.failed), report.chunks_uploaded,
    )
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
