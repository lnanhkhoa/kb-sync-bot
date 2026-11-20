# Daily job (Docker + DigitalOcean App Platform)

```bash
docker build -t optibot-job .
docker run --rm -e API_KEY=... optibot-job main.py   # one run, exit 0 (1 if any article failed to upload)
```

Each run of `main.py`:

1. Re-scrapes the help center.
2. Detects new or changed articles by comparing a SHA-256 of each Markdown file with the `content_hash` on
   its documents. See [knowledge-base.md](knowledge-base.md).
3. Uploads only that delta.

Unchanged articles are skipped. Articles that are no longer scraped are pruned from the store.

| Env var | Default | Meaning |
| --- | --- | --- |
| `GEMINI_API_KEY` (or `API_KEY`) | required | Gemini API key |
| `SCRAPE_LIMIT` | `40` | articles scraped and kept in the store; `0` = all |
| `SCRAPE_INCLUDE` | `how-to-use-youtube-with-optisigns` | comma-separated slugs that are always scraped |
| `ARTICLES_DIR` | `articles` | scrape output directory |
| `GEMINI_STORE_DISPLAY_NAME` | `optibot-kb` | File Search store name |

The final log line of a run looks like this:

```
run complete in 9s: scraped=40 added=0 updated=0 skipped=40 removed=0 failed=0 chunks_uploaded=0
```

## Deploy

`.do/app.yaml` defines an App Platform **scheduled job**, `daily-sync`, with `cron: 0 2 * * *` (UTC). It
builds the Dockerfile from the public GitHub repo.

```bash
doctl auth init
doctl apps create --spec .do/app.yaml   # then set GEMINI_API_KEY as an encrypted env var on the job
```

## Logs

- [last-run.log](last-run.log) is the log of the first deployed run. It was pulled with
  `doctl apps logs <app-id> daily-sync --type job --job-invocation <id>`.
- The account owner can see live logs in the console:
  <https://cloud.digitalocean.com/apps/6b6996b9-7855-4722-bc0a-0644deae6c08/logs>.
