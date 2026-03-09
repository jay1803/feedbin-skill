"""Archive workflow orchestration for feedbin-cli."""

from __future__ import annotations

import http.client
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .content import normalize_media_url
from .orgmode import continue_orgmode_import, integrate_with_orgmode
from .storage import process_entries, read_blacklist

MAX_LIMIT = 100


def log(message: str) -> None:
    print(message, file=sys.stderr)


def _is_retryable_download_error(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in {408, 425, 429, 500, 502, 503, 504}

    reason = getattr(exc, "reason", exc)
    reason_text = str(reason).lower()
    retry_signatures = (
        "unexpected_eof_while_reading",
        "eof occurred in violation of protocol",
        "ssl",
        "tls",
        "timed out",
        "timeout",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
        "remote end closed connection without response",
        "incompleteread",
    )

    direct_retryable = isinstance(
        exc,
        (
            TimeoutError,
            ConnectionError,
            ConnectionResetError,
            ConnectionAbortedError,
            BrokenPipeError,
            EOFError,
            ssl.SSLError,
            socket.timeout,
            http.client.IncompleteRead,
        ),
    )
    return direct_retryable or any(sig in reason_text for sig in retry_signatures)


def _read_url_bytes(req: urllib.request.Request, client: Any) -> bytes:
    attempts = max(1, int(getattr(client.config, "max_retries", 1) or 1))
    backoff_base = float(getattr(client.config, "retry_backoff_sec", 0.8) or 0.8)
    timeout = float(getattr(client.config, "timeout_sec", 30.0) or 30.0)

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001 - urlopen can raise EOF/SSL/socket variants directly
            last_error = exc
            is_last_attempt = attempt >= attempts
            if is_last_attempt or not _is_retryable_download_error(exc):
                break
            time.sleep(backoff_base * (2 ** (attempt - 1)))

    assert last_error is not None
    raise last_error


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
        raw = _read_url_bytes(req, client).decode("utf-8").strip()
        if not raw:
            return None
        payload = json.loads(raw)
        if isinstance(payload, dict):
            content = payload.get("content")
            if isinstance(content, str):
                return content
    except (json.JSONDecodeError, ValueError) as exc:
        log(f"Failed to parse extracted content from {extracted_url}: {exc}")
    except Exception as exc:  # noqa: BLE001 - keep archive pull resilient to transient download issues
        log(f"Failed to fetch extracted content from {extracted_url}: {exc}")
    return None


def download_binary_content(client: Any, media_url: str) -> bytes | None:
    if not media_url:
        return None

    normalized_url = normalize_media_url(media_url)

    req = urllib.request.Request(
        url=normalized_url,
        method="GET",
        headers={
            "Authorization": client._auth_header(),
            "User-Agent": "feedbin-cli/0.3",
        },
    )

    try:
        blob = _read_url_bytes(req, client)
        return blob or None
    except Exception as auth_exc:  # noqa: BLE001 - preserve archive flow on flaky media hosts
        # Some podcast hosts reject requests with Feedbin auth header; retry unauthenticated.
        try:
            req_no_auth = urllib.request.Request(
                url=normalized_url,
                method="GET",
                headers={"User-Agent": "feedbin-cli/0.3"},
            )
            blob = _read_url_bytes(req_no_auth, client)
            if blob:
                return blob
        except Exception as no_auth_exc:  # noqa: BLE001 - keep archive pull resilient
            log(
                f"Failed to download media from {normalized_url}: "
                f"auth attempt={_summarize_error(auth_exc)}; unauth attempt={_summarize_error(no_auth_exc)}"
            )
            return None

        log(f"Failed to download media from {normalized_url}: {_summarize_error(auth_exc)}")
        return None


def _parse_explicit_ids(ids_text: str) -> list[int]:
    values: list[int] = []
    for piece in ids_text.split(","):
        item = piece.strip()
        if not item:
            continue
        try:
            entry_id = int(item)
        except ValueError as exc:
            raise SystemExit(f"Invalid id '{item}'. IDs must be integers.") from exc
        if entry_id <= 0:
            raise SystemExit(f"Invalid id '{entry_id}'. IDs must be positive.")
        values.append(entry_id)

    if not values:
        raise SystemExit("No valid IDs were provided.")
    return list(dict.fromkeys(values))


def _fetch_entry_ids(client: Any, *, starred: bool, max_limit: int, explicit_ids: str | None = None) -> list[int]:
    if explicit_ids:
        return _parse_explicit_ids(explicit_ids)[:max_limit]

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
    payload = client.request(
        "GET",
        "entries.json",
        params={
            "ids": ",".join(str(i) for i in entry_ids),
            "mode": "extended",
            "include_enclosure": "true",
        },
    )
    if not isinstance(payload, list):
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


def _summarize_error(exc: Exception, *, limit: int = 180) -> str:
    text = str(exc).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _fetch_feeds(client: Any, entries: list[dict]) -> dict[int, dict]:
    feed_ids: list[int] = []
    for entry in entries:
        feed_id = entry.get("feed_id")
        if isinstance(feed_id, int):
            feed_ids.append(feed_id)

    unique_feed_ids = sorted(set(feed_ids))
    if not unique_feed_ids:
        return {}

    feeds: dict[int, dict] = {}

    # Feedbin does not reliably support feeds.json?ids=..., so this may 404.
    # Treat feed metadata as best-effort and continue with per-feed fallbacks.
    try:
        payload = client.request("GET", "feeds.json", params={"ids": ",".join(str(i) for i in unique_feed_ids)})
    except Exception as exc:  # noqa: BLE001 - keep archive pull resilient to metadata errors
        log(
            "Feed metadata bulk fetch failed at /feeds.json?ids=... "
            f"({_summarize_error(exc)}); falling back to per-feed requests"
        )
        payload = None

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and isinstance(item.get("id"), int):
                feeds[item["id"]] = item

    missing_ids = [feed_id for feed_id in unique_feed_ids if feed_id not in feeds]
    for feed_id in missing_ids:
        try:
            item = client.request("GET", f"feeds/{feed_id}.json")
        except Exception as exc:  # noqa: BLE001 - metadata is optional for archive output
            log(
                f"Feed metadata unavailable at /feeds/{feed_id}.json "
                f"({_summarize_error(exc)}); using fallback feed title"
            )
            continue

        if isinstance(item, dict) and isinstance(item.get("id"), int):
            feeds[item["id"]] = item

    return feeds


def run_pull(client: Any, args: Any) -> int:
    if args.unstar and not args.starred and not args.ids:
        raise SystemExit("--unstar can only be used with --starred or --ids")

    if args.ids and args.starred:
        raise SystemExit("Use either --ids or --starred, not both")

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

    entry_ids = _fetch_entry_ids(client, starred=bool(args.starred), max_limit=max_limit, explicit_ids=args.ids)
    if not entry_ids:
        if args.ids:
            log("No matching IDs to process")
        else:
            log("No starred entries found" if args.starred else "No unread entries found")
        return 0

    entries = _fetch_entries(client, entry_ids)
    feeds = _fetch_feeds(client, entries)

    processed_ids, entry_files = process_entries(
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
            entry_files,
            org_roam_dir,
            reading_index_file,
            log=log,
        )
        log(f"Created {len(org_processed)} org-roam files")

    if args.ids:
        if args.unstar:
            client.request("DELETE", "starred_entries.json", body={"starred_entries": processed_ids})
            log(f"Unstarred {len(processed_ids)} entries")
        else:
            log(f"Downloaded {len(processed_ids)} entries from --ids (use --unstar to remove stars)")
    elif args.starred:
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
