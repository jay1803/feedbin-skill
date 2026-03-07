# feedbin-cli skill

Terminal-friendly OpenClaw skill for deterministic Feedbin workflows.

## Overview

`feedbin-cli` wraps Feedbin API operations so agents can reliably triage feeds and entries without browser automation.

## Features

- List and filter Feedbin entries, subscriptions, tags, and saved searches
- Mark entries read/unread and star/unstar in bulk or by ID
- Manage subscriptions and tagging metadata
- Save URLs as Feedbin pages
- Archive unread/starred entries to local Markdown folders
- Optional org-roam integration (moves markdown + podcast MP3s into attachment paths, with ref-only notes for video URLs)

## Quick start

1. Install this skill in your OpenClaw skills directory.
2. Copy `.env.example` to `.env` and fill in your Feedbin credentials.
3. Run standard Feedbin commands or archive workflows from `scripts/feedbin_cli.py`.
4. For full command guidance and constraints, read [`SKILL.md`](./SKILL.md).

### Environment loading (default)

By default, the CLI auto-loads environment variables from:

1. `scripts/.env` (same folder as `feedbin_cli.py`)
2. `./.env` (current working directory)
3. `~/.env` (home fallback)

You can override with `--env-file /path/to/.env`.

### Legacy feedbin-script archive env compatibility

`archive pull` supports legacy env defaults when equivalent CLI flags are omitted:

- `FEEDBIN_OUTPUT` → `--output`
- `FEEDBIN_MAX` → `--max`
- `FEEDBIN_BLACKLIST` → `--blacklist`
- `FEEDBIN_STARRED=true` → `--starred`
- `FEEDBIN_UNSTAR=true` → `--unstar`
- `FEEDBIN_ORG_ROAM` → `--org-roam`
- `FEEDBIN_READING_INDEX` → `--reading-index`

CLI flags always take precedence over env defaults.

## Archive workflow examples

```bash
# Pull unread entries into ./output and mark them read
python3 scripts/feedbin_cli.py archive pull --max 30

# Pull starred entries and keep stars
python3 scripts/feedbin_cli.py archive pull --starred --output ~/Downloads/feedbin

# Pull specific entry IDs (same archive flow, without starred lookup)
python3 scripts/feedbin_cli.py archive pull --ids 5132165195,5132165000 --output ~/Downloads/feedbin

# Pull starred entries and unstar after successful archive
python3 scripts/feedbin_cli.py archive pull --starred --unstar --max 20

# Pull + create org-roam notes and move markdown/podcast MP3 files into attachments
python3 scripts/feedbin_cli.py archive pull \
  --starred \
  --org-roam ~/org-roam \
  --reading-index ~/org/reading.org

# Continue org-roam import later from existing markdown files
python3 scripts/feedbin_cli.py archive continue-org-roam \
  --output ~/Downloads/feedbin \
  --org-roam ~/org-roam
```

## Safety notes

- This skill can mutate account state (read/unread, stars, subscriptions, tags).
- Prefer read-only checks before bulk updates.
- Confirm account/context before destructive operations.
- `archive pull` marks unread items as read when archived.
- `archive pull --starred --unstar` removes stars only after successful local processing.

## Documentation

- Primary instructions: [`SKILL.md`](./SKILL.md)
- API mapping: [`references/feedbin-api-map.md`](./references/feedbin-api-map.md)
- Archive format: [`references/archive-format.md`](./references/archive-format.md)
- Security policy: [`SECURITY.md`](./SECURITY.md)
- Version: [`VERSION`](./VERSION)
