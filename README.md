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
- Optional org-roam integration (including ref-only notes for video URLs)

## Quick start

1. Install this skill in your OpenClaw skills directory.
2. Export Feedbin credentials (`FEEDBIN_EMAIL`, `FEEDBIN_PASSWORD`) or provide `--env-file`.
3. Run standard Feedbin commands or archive workflows from `scripts/feedbin_cli.py`.
4. For full command guidance and constraints, read [`SKILL.md`](./SKILL.md).

## Archive workflow examples

```bash
# Pull unread entries into ./output and mark them read
python3 scripts/feedbin_cli.py archive pull --max 30

# Pull starred entries and keep stars
python3 scripts/feedbin_cli.py archive pull --starred --output ~/Downloads/feedbin

# Pull starred entries and unstar after successful archive
python3 scripts/feedbin_cli.py archive pull --starred --unstar --max 20

# Pull + create org-roam notes and move markdown into attachments
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
