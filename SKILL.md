---
name: feedbin-cli
description: Manage Feedbin RSS feeds and entries through the Feedbin API, including read/unread, star/unstar, subscription CRUD, tag/tagging management, saved searches, saved pages, and archive downloads into Markdown/org-roam. Use when an agent needs deterministic terminal workflows for Feedbin triage or archive automation. Not for non-Feedbin readers, browser-only UI automation, or unrelated inbox/newsletter tooling.
---

# Feedbin CLI

Use the bundled CLI for deterministic Feedbin API operations with environment-based authentication.

## Quick start

Set credentials and point `FEEDBIN_CLI` to the script in this skill:

```bash
export FEEDBIN_EMAIL="you@example.com"
export FEEDBIN_PASSWORD="your-feedbin-password"
export FEEDBIN_CLI="$HOME/.openclaw/skills/feedbin-cli/scripts/feedbin_cli.py"
```

Optional environment variables:

- `FEEDBIN_BASE_URL` (default: `https://api.feedbin.com/v2`)
- `FEEDBIN_TIMEOUT_SEC` (default: `30`)
- `FEEDBIN_MAX_RETRIES` (default: `3`)
- `FEEDBIN_RETRY_BACKOFF_SEC` (default: `0.8`)

Env loading behavior:

- Auto-load `.env` from current directory, then `~/.env` (missing keys only).
- Pass `--env-file /path/to/.env` to load an explicit file.
- Pass `--no-auto-env` to disable auto-loading.

Run a credential check first:

```bash
python3 "$FEEDBIN_CLI" auth check
```

## Common API workflows

### List and inspect entries

```bash
python3 "$FEEDBIN_CLI" entries list --read false --per-page 50
python3 "$FEEDBIN_CLI" entries get 123456
```

### Mark entries read or unread

```bash
python3 "$FEEDBIN_CLI" entries mark-read --ids 1001,1002 --yes
python3 "$FEEDBIN_CLI" entries mark-unread --ids 1001,1002
```

### Star and unstar entries

```bash
python3 "$FEEDBIN_CLI" entries star --ids 1001,1002
python3 "$FEEDBIN_CLI" entries unstar --ids 1001,1002 --yes
```

### Use filter-based selection for entry mutations

```bash
python3 "$FEEDBIN_CLI" entries mark-read --feed-id 47 --read false --limit 100 --yes
python3 "$FEEDBIN_CLI" entries star --starred false --since "2026-02-01T00:00:00Z" --limit 50
```

### Manage subscriptions

```bash
python3 "$FEEDBIN_CLI" subscriptions list
python3 "$FEEDBIN_CLI" subscriptions add --feed-url "https://example.com/feed.xml"
python3 "$FEEDBIN_CLI" subscriptions rename 525 --title "Custom Title"
python3 "$FEEDBIN_CLI" subscriptions remove 525 --yes
```

### Save a URL to Feedbin pages

```bash
python3 "$FEEDBIN_CLI" pages save --url "https://example.com/article"
python3 "$FEEDBIN_CLI" pages save --url "https://example.com/post" --title "Fallback Title"
```

## Archive workflows

### Pull unread or starred entries to Markdown

```bash
python3 "$FEEDBIN_CLI" archive pull --max 30
python3 "$FEEDBIN_CLI" archive pull --starred --output ~/Downloads/feedbin
python3 "$FEEDBIN_CLI" archive pull --starred --unstar --max 20
```

Behavior:

- `archive pull` downloads entries to `--output` (default `output/`) grouped by feed.
- Unread mode marks successfully archived entries as read.
- Starred mode leaves stars by default; add `--unstar` to remove stars after successful archive.
- `--blacklist` supports feed IDs or feed titles (one per line).
- `--max` is capped to 100.

### Org-roam integration

```bash
python3 "$FEEDBIN_CLI" archive pull --starred --org-roam ~/org-roam --reading-index ~/org/reading.org
python3 "$FEEDBIN_CLI" archive continue-org-roam --output ~/Downloads/feedbin --org-roam ~/org-roam
```

Behavior:

- `--org-roam` creates `.org` ref files and moves markdown to org-roam attachment paths.
- Supported video URLs (e.g., YouTube) become ref-only org files when `--org-roam` is enabled.
- `continue-org-roam` imports previously downloaded markdown files without contacting Feedbin.

## Safety rules

Require `--yes` for destructive API actions:

- `entries mark-read`
- `entries unstar`
- `subscriptions remove`
- `pages remove`
- `taggings remove`
- `tags delete`
- `saved-searches remove`

Archive safety notes:

- `archive pull` mutates state intentionally (marks unread as read, optional unstar for starred).
- `archive continue-org-roam` is local-file only; it does not call Feedbin.

## Selector and limit rules

For entry mutation commands (`mark-read`, `mark-unread`, `star`, `unstar`):

- Use exactly one selector mode:
  - `--ids <comma-separated-ids>`
  - filter mode with one or more of `--feed-id`, `--read`, `--starred`, `--since`, `--page`, `--per-page`, `--limit`
- Do not combine `--ids` with filters.
- Mutation payloads are capped at 1,000 IDs.
- `entries list --ids` is capped at 100 IDs.

## Output behavior

- Pretty JSON output by default for API commands.
- ID-array responses print compact JSON arrays.
- Archive commands emit progress logs to stderr and write markdown/org files locally.

## References

- `references/feedbin-api-map.md` for endpoint mapping and command behavior
- `references/archive-format.md` for archive output format and org-roam details
