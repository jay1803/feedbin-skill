"""Archive workflow orchestration for feedbin-cli."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .orgmode import continue_orgmode_import, integrate_with_orgmode
from .storage import process_entries, read_blacklist

MAX_LIMIT = 100


def log(message: str) -> None:
    print(message, file=sys.stderr)


def fetch_extracted_content(client: Any, extracted_url: str) -> str | None:
    if not extracted_url:
        return None

    req = urllib.request.Request(
        url=extracted_url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": client._auth_header(),  # reuse existing client auth + settings
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=client.config.timeout_sec) as response:
            raw = response.read().decode("utf-8").strip()
        if not raw:
            return None
        payload = json.loads(raw)
        if isinstance(payload, dict):
            content = payload.get("content")
            if isinstance(content, str):
                return content
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError) as exc:
        log(f"Failed to fetch extracted content from {extracted_url}: {exc}")
    return None


def download_binary_content(client: Any, media_url: str) -> bytes | None:
    if not media_url:
        return None

    req = urllib.request.Request(
        url=media_url,
        method="GET",
        headers={
            "Authorization": client._auth_header(),
            "User-Agent": "feedbin-cli/0.3",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=client.config.timeout_sec) as response:
            blob = response.read()
        return blob or None
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
        log(f"Failed to download media from {media_url}: {exc}")
        return None


def _fetch_entry_ids(client: Any, *, starred: bool, max_limit: int) -> list[int]:
    path = "starred_entries.json" if starred else "unread_entries.json"
    payload = client.request("GET", path)
    if not isinstance(payload, list):
        return []

    ids: list[int] = []
    for item in payload:
        if isinstance(item, int):
            ids.append(item)
    return ids[:max_limit]


def _fetch_entries(client: Any, entry_ids: list[int]) -> list[dict]:
    if not entry_ids:
        return []
    payload = client.request("GET", "entries.json", params={"ids": ",".join(str(i) for i in entry_ids)})
    if not isinstance(payload, list):
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


def _fetch_feeds(client: Any, entries: list[dict]) -> dict[int, dict]:
    feed_ids: list[int] = []
    for entry in entries:
        feed_id = entry.get("feed_id")
        if isinstance(feed_id, int):
            feed_ids.append(feed_id)

    if not feed_ids:
        return {}

    payload = client.request("GET", "feeds.json", params={"ids": ",".join(str(i) for i in sorted(set(feed_ids)))})
    if not isinstance(payload, list):
        return {}

    feeds: dict[int, dict] = {}
    for item in payload:
        if isinstance(item, dict) and isinstance(item.get("id"), int):
            feeds[item["id"]] = item
    return feeds


def run_pull(client: Any, args: Any) -> int:
    if args.unstar and not args.starred:
        raise SystemExit("--unstar can only be used with --starred")

    requested_max = int(args.max)
    if requested_max < 1:
        raise SystemExit("--max must be at least 1")
    max_limit = min(requested_max, MAX_LIMIT)
    if requested_max > MAX_LIMIT:
        log(f"Max download capped at {MAX_LIMIT}; requested {requested_max}")

    output_dir = Path(args.output).expanduser().resolve()

    blacklist_path = Path(args.blacklist).expanduser().resolve() if args.blacklist else None
    try:
        blacklist_ids, blacklist_titles = read_blacklist(blacklist_path)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc

    entry_ids = _fetch_entry_ids(client, starred=bool(args.starred), max_limit=max_limit)
    if not entry_ids:
        log("No starred entries found" if args.starred else "No unread entries found")
        return 0

    entries = _fetch_entries(client, entry_ids)
    feeds = _fetch_feeds(client, entries)

    processed_ids, markdown_files = process_entries(
        entries,
        feeds,
        output_dir,
        blacklist_ids,
        blacklist_titles,
        fetch_extracted=lambda url: fetch_extracted_content(client, url),
        download_binary=lambda url: download_binary_content(client, url),
        log=log,
        video_ref_only=bool(args.org_roam),
    )

    if not processed_ids:
        log("All candidate entries were skipped (likely due to blacklist)")
        return 0

    if args.org_roam:
        org_roam_dir = Path(args.org_roam).expanduser().resolve()
        if not org_roam_dir.is_dir():
            raise SystemExit(f"Org-roam directory not found: {org_roam_dir}")

        reading_index_file = None
        if args.reading_index:
            reading_index_file = Path(args.reading_index).expanduser().resolve()
            if not reading_index_file.exists():
                raise SystemExit(f"Reading index file not found: {reading_index_file}")

        processed_entries = [entry for entry in entries if entry.get("id") in processed_ids]
        org_processed = integrate_with_orgmode(
            processed_entries,
            feeds,
            markdown_files,
            org_roam_dir,
            reading_index_file,
            log=log,
        )
        log(f"Created {len(org_processed)} org-roam files")

    if args.starred:
        if args.unstar:
            client.request("DELETE", "starred_entries.json", body={"starred_entries": processed_ids})
            log(f"Unstarred {len(processed_ids)} entries")
        else:
            log(f"Downloaded {len(processed_ids)} starred entries (use --unstar to remove stars)")
    else:
        client.request("DELETE", "unread_entries.json", body={"unread_entries": processed_ids})
        log(f"Marked {len(processed_ids)} entries as read")

    log("Done")
    return 0


def run_continue_org_roam(args: Any) -> int:
    output_dir = Path(args.output).expanduser().resolve()
    org_roam_dir = Path(args.org_roam).expanduser().resolve()
    if not org_roam_dir.is_dir():
        raise SystemExit(f"Org-roam directory not found: {org_roam_dir}")

    reading_index_file = None
    if args.reading_index:
        reading_index_file = Path(args.reading_index).expanduser().resolve()
        if not reading_index_file.exists():
            raise SystemExit(f"Reading index file not found: {reading_index_file}")

    processed = continue_orgmode_import(
        output_dir,
        org_roam_dir,
        reading_index_file,
        log=log,
    )
    log(f"Created {len(processed)} org-roam files from existing markdown")
    log("Done")
    return 0
