---
name: feedbin-cli
description: Manage Feedbin RSS feeds and entries through the Feedbin API, including read/unread, star/unstar, subscription CRUD, tag/tagging management, saved searches, and saving URLs as pages. Use when an agent needs deterministic terminal workflows for Feedbin triage or subscription administration. Not for non-Feedbin readers, browser-only UI automation, or unrelated inbox/newsletter tooling.
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

## Common workflows

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

## Safety rules

Require `--yes` for destructive actions:

- `entries mark-read`
- `entries unstar`
- `subscriptions remove`
- `pages remove`
- `taggings remove`
- `tags delete`
- `saved-searches remove`

Without `--yes`, the CLI fails fast and does not execute the API call.

## Selector and limit rules

For entry mutation commands (`mark-read`, `mark-unread`, `star`, `unstar`):

- Use exactly one selector mode:
  - `--ids <comma-separated-ids>`
  - filter mode with one or more of `--feed-id`, `--read`, `--starred`, `--since`, `--page`, `--per-page`, `--limit`
- Do not combine `--ids` with filters.
- Mutation payloads are capped at 1,000 IDs.
- `entries list --ids` is capped at 100 IDs.

## Output behavior

- Pretty JSON output by default.
- ID-array responses print compact JSON arrays.

## References

Read `references/feedbin-api-map.md` for endpoint mapping, payload keys, and status behavior.
