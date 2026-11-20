# OptiBot mini-clone

This project scrapes the OptiSigns help center (Zendesk API) into clean Markdown and syncs it into a Google
Gemini File Search store. The assistant answers from that store, and a daily job on DigitalOcean re-scrapes
the help center and uploads only the articles that changed.

## Setup

```bash
uv sync                       # Python ≥ 3.11
cp .env.sample .env           # set GEMINI_API_KEY (Google AI Studio key)
```

## Run locally

```bash
make scrape      # 40 articles -> articles/<slug>.md (pinned YouTube how-to + 39 most recently updated)
make upload      # sync articles/ to the File Search store "optibot-kb" (delta only, prunes removed articles)
make ask Q="How do I add a YouTube video?"
make job         # what the daily job runs: scrape + delta upload  (= python main.py)
make docker-build && docker run --rm -e API_KEY=... optibot main.py   # one run, exits 0
make test        # 20 tests, no network needed
```

## How it works

- **Scrape**: `optibot/scrape.py` and `optibot/markdown.py`. Nav and ads are never fetched. Headings, code
  blocks and TOC anchors are preserved, and links to other scraped articles become relative `./<slug>.md`
  links. Details: [docs/scraping.md](docs/scraping.md).
- **Chunking**: chunks are cut at headings, at most 450 words each. Every chunk starts with the article
  title and its `Article URL:` line, so any retrieved chunk can be cited. Gemini keeps each chunk whole, so
  1 document = 1 chunk and the logged count is exact. Details:
  [docs/knowledge-base.md](docs/knowledge-base.md).
- **Upload log**: for example
  `embedded 258 chunks from 40 files | added=40 updated=0 skipped=0 removed=0 failed=0`.
- **Delta**: the SHA-256 of each Markdown file is compared with the `content_hash` stored on its Gemini
  documents. The result is added / updated / skipped / removed. Flow: [docs/delta-sync.png](docs/delta-sync.png).
- **Assistant**: Gemini File Search with the system prompt from the assignment, word for word
  (`optibot/assistant.py`). It uses Gemini because the OpenAI Assistants API was shut down on 2026-08-26.

## Daily job

`main.py` is packaged with the `Dockerfile` and runs as a DigitalOcean App Platform scheduled job
(`.do/app.yaml`, every day at 02:00 UTC). Details: [docs/deployment.md](docs/deployment.md).

- **Last run artefact**: [docs/last-run.log](docs/last-run.log)
- **Live logs** (account owner):
  <https://cloud.digitalocean.com/apps/6b6996b9-7855-4722-bc0a-0644deae6c08/logs>

## Sample answer

`make ask Q="How do I add a YouTube video?"`:

```
* Go to **Files/Assets** in the portal and select **Apps**.
* Search for and select the **YouTube** app.
* Paste your video link into the **URL** field and adjust the **Name** if desired.
* (Optional) Configure settings under **Display options** (Mute, Captions) and **Playback Options** (Start At, End At).
* Click **Save** to save the video asset to your library.

Article URL: https://support.optisigns.com/hc/en-us/articles/360051014713-How-to-Use-YouTube-with-OptiSigns
```

Tests: [docs/testing.md](docs/testing.md).
