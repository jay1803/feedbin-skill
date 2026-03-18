# Archive Output Format

This document defines the local file/output behavior for `scripts/feedbin_cli.py archive ...` commands.

## Markdown output layout (`archive pull`)

Default root: `--output output`

Structure:

```text
output/
  <feed-slug>/
    <entry-slug>.md
```

- Feed folder name is slugified from feed title.
- Entry filename is slugified from entry title.
- If a conflicting filename exists, numeric suffixes are used (`-2`, `-3`, ...).

## Markdown document shape

Each generated file is UTF-8 markdown with a metadata header block:

```markdown
# <entry title>

*Source:* <feed title>
*URL:* <canonical article url>         # present when URL exists
*Feed URL:* <feed url>                 # fallback when article URL missing
*Published:* YYYY-MM-DD HH:MM:SS +0000 # when timestamp exists

<markdown body converted from content/summary/extracted content>
```

Content source priority:

1. `entry.extracted_content_url` JSON `content` (when available)
2. `entry.content`
3. `entry.summary`

Pandoc behavior:

- If `pandoc` is available on PATH, conversion uses `pandoc --from=html --to=gfm`.
- Otherwise a built-in fallback converter is used.

## Org-roam mode (`archive pull --org-roam ...`)

When `--org-roam` is provided:

1. Markdown files are created first (except video ref-only cases).
2. Audio entries keep both outputs locally during archive: the article markdown plus the podcast `.mp3` when one is available.
3. For each processed entry, an org-roam `.org` note is created at:
   - `<org-roam>/<timestamp>-<slug>.org`
4. All archived files for that entry are moved into the same org-roam attachment directory:
   - `<org-roam>/data/<first-two-uuid-chars>/<remaining-uuid-with-dashes>/<markdown-file>`
   - `<org-roam>/data/<first-two-uuid-chars>/<remaining-uuid-with-dashes>/<podcast-file>.mp3`

Org file content:

```org
:PROPERTIES:
:ID:       <uuid>
:ROAM_REFS: <url>
:END:
#+title: <entry title>
#+filetags: :ref:
```

Optional reading index:

- If `--reading-index` is provided, this line is appended:
  - `** HOLD [[id:<uuid>][<title>]]`

Duplicate handling:

- Existing `:ROAM_REFS:` URLs in existing org files are detected.
- If URL already exists, entry is skipped for org import and the duplicate file left in `--output` is deleted.

## Video URL ref-only behavior

If `--org-roam` is enabled and entry URL hostname matches known video hosts (YouTube variants):

- No markdown file is created.
- A ref-only `.org` note is still created with `:ROAM_REFS:`.

## Continue mode (`archive continue-org-roam`)

This command imports existing markdown files from `--output` into org-roam:

- Does not call Feedbin API.
- Reads metadata from markdown headers (`#`, `*Source:*`, `*URL:*`).
- Moves markdown to attachments and creates corresponding org ref notes.
- Supports optional `--reading-index` updates.
