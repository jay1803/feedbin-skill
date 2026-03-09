#!/usr/bin/env python3
"""Feedbin CLI helper for common feed and entry management workflows."""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import shlex
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from downloader import workflow as archive_workflow

DEFAULT_BASE_URL = "https://api.feedbin.com/v2"
DEFAULT_TIMEOUT_SEC = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SEC = 0.8
MAX_MUTATION_IDS = 1000
MAX_ENTRY_IDS_QUERY = 100


class CliError(Exception):
    """User-facing command error."""


@dataclass
class FeedbinConfig:
    email: str
    password: str
    base_url: str
    timeout_sec: float
    max_retries: int
    retry_backoff_sec: float


class FeedbinClient:
    def __init__(self, config: FeedbinConfig):
        self.config = config

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        cleaned_path = path.lstrip("/")
        base = self.config.base_url.rstrip("/")
        url = f"{base}/{cleaned_path}"
        query: dict[str, str] = {}
        if params:
            for key, value in params.items():
                if value is None:
                    continue
                query[key] = str(value)
        if query:
            return f"{url}?{urllib.parse.urlencode(query)}"
        return url

    def _auth_header(self) -> str:
        raw = f"{self.config.email}:{self.config.password}".encode("utf-8")
        token = base64.b64encode(raw).decode("ascii")
        return f"Basic {token}"

    def _is_retryable_url_error(self, exc: urllib.error.URLError) -> bool:
        reason_text = str(getattr(exc, "reason", exc)).lower()
        retry_signatures = (
            "unexpected_eof_while_reading",
            "eof occurred in violation of protocol",
            "ssl",
            "tls",
            "timed out",
            "connection reset",
            "temporarily unavailable",
            "incompleteread",
            "connection aborted",
            "remote end closed connection without response",
        )
        return any(sig in reason_text for sig in retry_signatures)

    def _is_retryable_request_error(self, exc: Exception) -> bool:
        if isinstance(exc, urllib.error.URLError):
            return self._is_retryable_url_error(exc)
        if isinstance(exc, urllib.error.HTTPError):
            return exc.code in {408, 425, 429, 500, 502, 503, 504}
        if isinstance(
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
                OSError,
            ),
        ):
            reason_text = str(exc).lower()
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
            )
            return any(sig in reason_text for sig in retry_signatures) or isinstance(
                exc,
                (
                    TimeoutError,
                    ConnectionResetError,
                    ConnectionAbortedError,
                    BrokenPipeError,
                    EOFError,
                    ssl.SSLError,
                    socket.timeout,
                    http.client.IncompleteRead,
                ),
            )
        return False

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        allow_empty: bool = True,
    ) -> Any:
        url = self._url(path, params)
        headers = {
            "Accept": "application/json",
            "Authorization": self._auth_header(),
        }
        payload: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            payload = json.dumps(body).encode("utf-8")

        request = urllib.request.Request(
            url=url,
            data=payload,
            method=method,
            headers=headers,
        )

        attempts = max(1, self.config.max_retries)
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_sec) as response:
                    raw = response.read().decode("utf-8").strip()
                    if not raw:
                        if allow_empty:
                            return None
                        raise CliError("Feedbin returned an empty response body")
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        return raw
            except urllib.error.HTTPError as exc:
                last_error = exc
                is_last_attempt = attempt >= attempts
                if is_last_attempt or not self._is_retryable_request_error(exc):
                    detail = ""
                    if exc.fp:
                        payload_text = exc.fp.read().decode("utf-8", errors="replace").strip()
                        if payload_text:
                            detail = f": {payload_text}"
                    raise CliError(f"HTTP {exc.code} {exc.reason}{detail}") from exc
                backoff = self.config.retry_backoff_sec * (2 ** (attempt - 1))
                time.sleep(backoff)
            except Exception as exc:  # noqa: BLE001 - network stack may raise non-URLError EOF/SSL exceptions
                last_error = exc
                is_last_attempt = attempt >= attempts
                if is_last_attempt or not self._is_retryable_request_error(exc):
                    break
                backoff = self.config.retry_backoff_sec * (2 ** (attempt - 1))
                time.sleep(backoff)

        if last_error is not None:
            detail = getattr(last_error, "reason", last_error)
            raise CliError(f"Request failed after {attempts} attempt(s): {detail}") from last_error

        raise CliError("Request failed for an unknown reason")


def bool_text(value: str) -> str:
    lowered = value.lower()
    if lowered in {"true", "1", "yes", "y"}:
        return "true"
    if lowered in {"false", "0", "no", "n"}:
        return "false"
    raise argparse.ArgumentTypeError("Expected one of: true, false")


def parse_ids(ids_text: str) -> list[int]:
    values: list[int] = []
    for piece in ids_text.split(","):
        item = piece.strip()
        if not item:
            continue
        try:
            entry_id = int(item)
        except ValueError as exc:
            raise CliError(f"Invalid id '{item}'. IDs must be integers.") from exc
        if entry_id <= 0:
            raise CliError(f"Invalid id '{entry_id}'. IDs must be positive.")
        values.append(entry_id)

    if not values:
        raise CliError("No valid IDs were provided.")

    if len(values) > MAX_MUTATION_IDS:
        raise CliError(f"Too many IDs ({len(values)}). Maximum is {MAX_MUTATION_IDS}.")

    deduped = list(dict.fromkeys(values))
    return deduped


def print_json(payload: Any, *, compact_ids: bool = False) -> None:
    if payload is None:
        print(json.dumps({"ok": True}, indent=2))
        return

    if compact_ids and isinstance(payload, list) and all(isinstance(item, int) for item in payload):
        print(json.dumps(payload, separators=(",", ":")))
        return

    print(json.dumps(payload, indent=2, ensure_ascii=True))


def _parse_env_line(line: str) -> tuple[str, str] | None:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None

    if raw.startswith("export "):
        raw = raw[len("export ") :].strip()

    if "=" not in raw:
        return None

    key, value = raw.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None

    if value and ((value[0] == value[-1]) and value[0] in {"\"", "'"}):
        value = value[1:-1]
    else:
        parts = shlex.split(value, comments=True, posix=True)
        value = parts[0] if parts else ""

    return key, value


def load_env_file(path: str) -> None:
    env_path = Path(path).expanduser()
    if not env_path.exists() or not env_path.is_file():
        raise CliError(f"Env file not found: {env_path}")

    try:
        content = env_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError(f"Failed to read env file {env_path}: {exc}") from exc

    for line in content.splitlines():
        parsed = _parse_env_line(line)
        if not parsed:
            continue
        key, value = parsed
        os.environ.setdefault(key, value)


def autoload_env() -> None:
    script_dir = Path(__file__).resolve().parent
    skill_root = script_dir.parent
    candidates = [
        skill_root / ".env",  # skill root (preferred)
        script_dir / ".env",  # legacy script-local fallback
        Path.cwd() / ".env",  # current working directory
        Path.home() / ".env",  # user home fallback
    ]
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists() and candidate.is_file():
            try:
                load_env_file(str(candidate))
            except CliError:
                # Ignore malformed optional auto env files; explicit --env-file remains strict.
                continue


def read_config() -> FeedbinConfig:
    email = os.getenv("FEEDBIN_EMAIL", "").strip()
    password = os.getenv("FEEDBIN_PASSWORD", "").strip()

    missing = []
    if not email:
        missing.append("FEEDBIN_EMAIL")
    if not password:
        missing.append("FEEDBIN_PASSWORD")

    if missing:
        joined = ", ".join(missing)
        raise CliError(f"Missing required environment variable(s): {joined}")

    base_url = os.getenv("FEEDBIN_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL

    timeout_raw = os.getenv("FEEDBIN_TIMEOUT_SEC", str(DEFAULT_TIMEOUT_SEC)).strip()
    try:
        timeout_sec = float(timeout_raw)
        if timeout_sec <= 0:
            raise ValueError
    except ValueError as exc:
        raise CliError("FEEDBIN_TIMEOUT_SEC must be a positive number.") from exc

    retries_raw = os.getenv("FEEDBIN_MAX_RETRIES", str(DEFAULT_MAX_RETRIES)).strip()
    try:
        max_retries = int(retries_raw)
        if max_retries <= 0:
            raise ValueError
    except ValueError as exc:
        raise CliError("FEEDBIN_MAX_RETRIES must be a positive integer.") from exc

    backoff_raw = os.getenv("FEEDBIN_RETRY_BACKOFF_SEC", str(DEFAULT_RETRY_BACKOFF_SEC)).strip()
    try:
        retry_backoff_sec = float(backoff_raw)
        if retry_backoff_sec < 0:
            raise ValueError
    except ValueError as exc:
        raise CliError("FEEDBIN_RETRY_BACKOFF_SEC must be a non-negative number.") from exc

    return FeedbinConfig(
        email=email,
        password=password,
        base_url=base_url,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        retry_backoff_sec=retry_backoff_sec,
    )


def require_yes(args: argparse.Namespace) -> None:
    if not getattr(args, "yes", False):
        raise CliError("This command is destructive. Re-run with --yes to confirm.")


def mutation_filter_values(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "feed_id": getattr(args, "feed_id", None),
        "read": getattr(args, "read", None),
        "starred": getattr(args, "starred", None),
        "since": getattr(args, "since", None),
        "page": getattr(args, "page", None),
        "per_page": getattr(args, "per_page", None),
        "limit": getattr(args, "limit", None),
    }


def resolve_entry_ids(client: FeedbinClient, args: argparse.Namespace) -> list[int]:
    ids_text = getattr(args, "ids", None)
    filters = mutation_filter_values(args)
    has_filters = any(value is not None for value in filters.values())

    if ids_text and has_filters:
        raise CliError("Use either --ids or query filters, not both.")
    if not ids_text and not has_filters:
        raise CliError(
            "No selector provided. Pass --ids or at least one filter (--feed-id/--read/--starred/--since/--page/--per-page/--limit)."
        )

    if ids_text:
        return parse_ids(ids_text)

    entries_params: dict[str, Any] = {
        "read": filters["read"],
        "starred": filters["starred"],
        "since": filters["since"],
        "page": filters["page"],
        "per_page": filters["per_page"],
    }
    feed_id = filters["feed_id"]
    path = "entries.json"
    if feed_id is not None:
        path = f"feeds/{feed_id}/entries.json"

    entries = client.request("GET", path, params=entries_params)
    if not isinstance(entries, list):
        raise CliError("Unexpected response while resolving entries.")

    ids: list[int] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if isinstance(entry_id, int):
            ids.append(entry_id)

    if filters["limit"] is not None:
        ids = ids[: int(filters["limit"])]

    ids = list(dict.fromkeys(ids))

    if not ids:
        raise CliError("Selector resolved to 0 entries.")

    if len(ids) > MAX_MUTATION_IDS:
        raise CliError(f"Selector resolved to {len(ids)} IDs. Maximum is {MAX_MUTATION_IDS}.")

    return ids


def add_entries_selector_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ids", help="Comma-separated entry IDs")
    parser.add_argument("--feed-id", type=int, help="Filter by feed ID")
    parser.add_argument("--read", type=bool_text, help="Filter entries by read state")
    parser.add_argument("--starred", type=bool_text, help="Filter entries by star state")
    parser.add_argument("--since", help="ISO 8601 timestamp")
    parser.add_argument("--page", type=int, help="Page number")
    parser.add_argument("--per-page", type=int, help="Results per page")
    parser.add_argument("--limit", type=int, help="Client-side limit after filter resolution")


def cmd_auth_check(client: FeedbinClient, _args: argparse.Namespace) -> int:
    response = client.request("GET", "authentication.json")
    if response is None:
        print_json({"ok": True})
    else:
        print_json(response)
    return 0


def entry_source(entry: dict[str, Any]) -> str:
    source = entry.get("feed_title")
    if isinstance(source, str) and source.strip():
        return source.strip()

    site_url = entry.get("site_url")
    if isinstance(site_url, str) and site_url.strip():
        parsed_site = urllib.parse.urlparse(site_url.strip())
        if parsed_site.netloc:
            return parsed_site.netloc

    url = entry.get("url")
    if isinstance(url, str) and url.strip():
        parsed_url = urllib.parse.urlparse(url.strip())
        if parsed_url.netloc:
            return parsed_url.netloc

    return ""


def cmd_entries_list(client: FeedbinClient, args: argparse.Namespace) -> int:
    if args.ids:
        parsed = parse_ids(args.ids)
        if len(parsed) > MAX_ENTRY_IDS_QUERY:
            raise CliError(f"entries list with --ids supports at most {MAX_ENTRY_IDS_QUERY} IDs.")

    params = {
        "ids": args.ids,
        "read": args.read,
        "starred": args.starred,
        "since": args.since,
        "page": args.page,
        "per_page": args.per_page,
        "mode": args.mode,
        "include_original": "true" if args.include_original else None,
        "include_enclosure": "true" if args.include_enclosure else None,
        "include_content_diff": "true" if args.include_content_diff else None,
    }

    if args.feed_id is not None:
        path = f"feeds/{args.feed_id}/entries.json"
    else:
        path = "entries.json"

    payload = client.request("GET", path, params=params)
    if args.limit is not None and isinstance(payload, list):
        payload = payload[: args.limit]

    if args.triage and isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            entry_id = item.get("id", "")
            title = item.get("title") or ""
            source = entry_source(item)
            url = item.get("url") or ""
            print(f"{entry_id} | {title} | {source} | {url}")
        return 0

    print_json(payload)
    return 0


def cmd_entries_get(client: FeedbinClient, args: argparse.Namespace) -> int:
    params = {
        "mode": args.mode,
        "include_original": "true" if args.include_original else None,
        "include_enclosure": "true" if args.include_enclosure else None,
        "include_content_diff": "true" if args.include_content_diff else None,
    }
    payload = client.request("GET", f"entries/{args.entry_id}.json", params=params)
    print_json(payload)
    return 0


def cmd_entries_mark_read(client: FeedbinClient, args: argparse.Namespace) -> int:
    require_yes(args)
    ids = resolve_entry_ids(client, args)
    payload = client.request("DELETE", "unread_entries.json", body={"unread_entries": ids})
    print_json(payload, compact_ids=True)
    return 0


def cmd_entries_mark_unread(client: FeedbinClient, args: argparse.Namespace) -> int:
    ids = resolve_entry_ids(client, args)
    payload = client.request("POST", "unread_entries.json", body={"unread_entries": ids})
    print_json(payload, compact_ids=True)
    return 0


def cmd_entries_star(client: FeedbinClient, args: argparse.Namespace) -> int:
    ids = resolve_entry_ids(client, args)
    payload = client.request("POST", "starred_entries.json", body={"starred_entries": ids})
    print_json(payload, compact_ids=True)
    return 0


def cmd_entries_unstar(client: FeedbinClient, args: argparse.Namespace) -> int:
    require_yes(args)
    ids = resolve_entry_ids(client, args)
    payload = client.request("DELETE", "starred_entries.json", body={"starred_entries": ids})
    print_json(payload, compact_ids=True)
    return 0


def cmd_subscriptions_list(client: FeedbinClient, args: argparse.Namespace) -> int:
    params = {
        "since": args.since,
        "mode": args.mode,
    }
    payload = client.request("GET", "subscriptions.json", params=params)
    print_json(payload)
    return 0


def cmd_subscriptions_get(client: FeedbinClient, args: argparse.Namespace) -> int:
    payload = client.request("GET", f"subscriptions/{args.subscription_id}.json")
    print_json(payload)
    return 0


def cmd_subscriptions_add(client: FeedbinClient, args: argparse.Namespace) -> int:
    payload = client.request("POST", "subscriptions.json", body={"feed_url": args.feed_url})
    print_json(payload)
    return 0


def cmd_subscriptions_rename(client: FeedbinClient, args: argparse.Namespace) -> int:
    body = {"title": args.title}
    if args.use_post_update:
        path = f"subscriptions/{args.subscription_id}/update.json"
        method = "POST"
    else:
        path = f"subscriptions/{args.subscription_id}.json"
        method = "PATCH"
    payload = client.request(method, path, body=body)
    print_json(payload)
    return 0


def cmd_subscriptions_remove(client: FeedbinClient, args: argparse.Namespace) -> int:
    require_yes(args)
    payload = client.request("DELETE", f"subscriptions/{args.subscription_id}.json")
    print_json(payload)
    return 0


def cmd_pages_save(client: FeedbinClient, args: argparse.Namespace) -> int:
    body = {"url": args.url}
    if args.title:
        body["title"] = args.title
    payload = client.request("POST", "pages.json", body=body)
    print_json(payload)
    return 0


def cmd_pages_remove(client: FeedbinClient, args: argparse.Namespace) -> int:
    require_yes(args)
    payload = client.request("DELETE", f"pages/{args.page_id}.json")
    print_json(payload)
    return 0


def cmd_taggings_list(client: FeedbinClient, _args: argparse.Namespace) -> int:
    payload = client.request("GET", "taggings.json")
    print_json(payload)
    return 0


def cmd_taggings_get(client: FeedbinClient, args: argparse.Namespace) -> int:
    payload = client.request("GET", f"taggings/{args.tagging_id}.json")
    print_json(payload)
    return 0


def cmd_taggings_add(client: FeedbinClient, args: argparse.Namespace) -> int:
    body = {"feed_id": args.feed_id, "name": args.name}
    payload = client.request("POST", "taggings.json", body=body)
    print_json(payload)
    return 0


def cmd_taggings_remove(client: FeedbinClient, args: argparse.Namespace) -> int:
    require_yes(args)
    payload = client.request("DELETE", f"taggings/{args.tagging_id}.json")
    print_json(payload)
    return 0


def cmd_tags_rename(client: FeedbinClient, args: argparse.Namespace) -> int:
    body = {"old_name": args.old_name, "new_name": args.new_name}
    payload = client.request("POST", "tags.json", body=body)
    print_json(payload)
    return 0


def cmd_tags_delete(client: FeedbinClient, args: argparse.Namespace) -> int:
    require_yes(args)
    payload = client.request("DELETE", "tags.json", body={"name": args.name})
    print_json(payload)
    return 0


def cmd_saved_searches_list(client: FeedbinClient, _args: argparse.Namespace) -> int:
    payload = client.request("GET", "saved_searches.json")
    print_json(payload)
    return 0


def cmd_saved_searches_get(client: FeedbinClient, args: argparse.Namespace) -> int:
    params = {
        "include_entries": "true" if args.include_entries else None,
        "page": args.page,
    }
    payload = client.request("GET", f"saved_searches/{args.saved_search_id}.json", params=params)
    compact_ids = not args.include_entries
    print_json(payload, compact_ids=compact_ids)
    return 0


def cmd_saved_searches_add(client: FeedbinClient, args: argparse.Namespace) -> int:
    body = {"name": args.name, "query": args.query}
    payload = client.request("POST", "saved_searches.json", body=body)
    print_json(payload)
    return 0


def cmd_saved_searches_update(client: FeedbinClient, args: argparse.Namespace) -> int:
    body: dict[str, Any] = {}
    if args.name is not None:
        body["name"] = args.name
    if args.query is not None:
        body["query"] = args.query
    if not body:
        raise CliError("Provide at least one field to update: --name and/or --query")

    if args.use_post_update:
        method = "POST"
        path = f"saved_searches/{args.saved_search_id}/update.json"
    else:
        method = "PATCH"
        path = f"saved_searches/{args.saved_search_id}.json"

    payload = client.request(method, path, body=body)
    print_json(payload)
    return 0


def cmd_saved_searches_remove(client: FeedbinClient, args: argparse.Namespace) -> int:
    require_yes(args)
    payload = client.request("DELETE", f"saved_searches/{args.saved_search_id}.json")
    print_json(payload)
    return 0


def _env_flag_true(name: str) -> bool:
    value = os.getenv(name)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _apply_archive_pull_legacy_env_defaults(args: argparse.Namespace) -> None:
    if args.output is None:
        env_output = os.getenv("FEEDBIN_OUTPUT", "").strip()
        args.output = env_output or "output"

    if args.max is None:
        env_max = os.getenv("FEEDBIN_MAX", "").strip()
        if env_max:
            try:
                args.max = int(env_max)
            except ValueError as exc:
                raise CliError("FEEDBIN_MAX must be an integer when used as archive pull default.") from exc
        else:
            args.max = 100

    if args.blacklist is None:
        env_blacklist = os.getenv("FEEDBIN_BLACKLIST", "").strip()
        if env_blacklist:
            args.blacklist = env_blacklist

    if args.org_roam is None:
        env_org_roam = os.getenv("FEEDBIN_ORG_ROAM", "").strip()
        if env_org_roam:
            args.org_roam = env_org_roam

    if args.reading_index is None:
        env_reading_index = os.getenv("FEEDBIN_READING_INDEX", "").strip()
        if env_reading_index:
            args.reading_index = env_reading_index

    if args.starred is None:
        args.starred = _env_flag_true("FEEDBIN_STARRED")

    if args.unstar is None:
        args.unstar = _env_flag_true("FEEDBIN_UNSTAR")


def cmd_archive_pull(client: FeedbinClient, args: argparse.Namespace) -> int:
    _apply_archive_pull_legacy_env_defaults(args)
    return archive_workflow.run_pull(client, args)


def cmd_archive_continue_org_roam(_client: FeedbinClient, args: argparse.Namespace) -> int:
    return archive_workflow.run_continue_org_roam(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage Feedbin entries, subscriptions, tags, pages, and saved searches.",
    )
    parser.add_argument(
        "--env-file",
        help="Optional .env file to load before reading FEEDBIN_* variables (values only set when missing).",
    )
    parser.add_argument(
        "--no-auto-env",
        action="store_true",
        help="Disable automatic .env loading from current directory and ~/.env.",
    )

    top = parser.add_subparsers(dest="group", required=True)

    auth = top.add_parser("auth", help="Authentication commands")
    auth_sub = auth.add_subparsers(dest="action", required=True)
    auth_check = auth_sub.add_parser("check", help="Validate API credentials")
    auth_check.set_defaults(handler=cmd_auth_check)

    entries = top.add_parser("entries", help="Entry management commands")
    entries_sub = entries.add_subparsers(dest="action", required=True)

    entries_list = entries_sub.add_parser("list", help="List entries")
    entries_list.add_argument("--feed-id", type=int, help="Optional feed ID scope")
    entries_list.add_argument("--ids", help="Comma-separated entry IDs (max 100)")
    entries_list.add_argument("--read", type=bool_text, help="Filter by read state")
    entries_list.add_argument("--starred", type=bool_text, help="Filter by star state")
    entries_list.add_argument("--since", help="ISO 8601 timestamp")
    entries_list.add_argument("--page", type=int, help="Page number")
    entries_list.add_argument("--per-page", type=int, help="Results per page")
    entries_list.add_argument("--mode", help="Use 'extended' for additional metadata")
    entries_list.add_argument("--include-original", action="store_true", help="Include original updated entry")
    entries_list.add_argument("--include-enclosure", action="store_true", help="Include enclosure metadata")
    entries_list.add_argument(
        "--include-content-diff",
        action="store_true",
        help="Include HTML content diff for updated entries",
    )
    entries_list.add_argument("--limit", type=int, help="Client-side item limit")
    entries_list.add_argument(
        "--triage",
        action="store_true",
        help="Print compact triage lines: ID | title | source | URL",
    )
    entries_list.set_defaults(handler=cmd_entries_list)

    entries_get = entries_sub.add_parser("get", help="Get one entry")
    entries_get.add_argument("entry_id", type=int)
    entries_get.add_argument("--mode", help="Use 'extended' for additional metadata")
    entries_get.add_argument("--include-original", action="store_true")
    entries_get.add_argument("--include-enclosure", action="store_true")
    entries_get.add_argument("--include-content-diff", action="store_true")
    entries_get.set_defaults(handler=cmd_entries_get)

    entries_mark_read = entries_sub.add_parser("mark-read", help="Mark entries as read")
    add_entries_selector_flags(entries_mark_read)
    entries_mark_read.add_argument("--yes", action="store_true", help="Confirm destructive action")
    entries_mark_read.set_defaults(handler=cmd_entries_mark_read)

    entries_mark_unread = entries_sub.add_parser("mark-unread", help="Mark entries as unread")
    add_entries_selector_flags(entries_mark_unread)
    entries_mark_unread.set_defaults(handler=cmd_entries_mark_unread)

    entries_star = entries_sub.add_parser("star", help="Star entries")
    add_entries_selector_flags(entries_star)
    entries_star.set_defaults(handler=cmd_entries_star)

    entries_unstar = entries_sub.add_parser("unstar", help="Unstar entries")
    add_entries_selector_flags(entries_unstar)
    entries_unstar.add_argument("--yes", action="store_true", help="Confirm destructive action")
    entries_unstar.set_defaults(handler=cmd_entries_unstar)

    subscriptions = top.add_parser("subscriptions", help="Subscription management commands")
    subscriptions_sub = subscriptions.add_subparsers(dest="action", required=True)

    subscriptions_list = subscriptions_sub.add_parser("list", help="List subscriptions")
    subscriptions_list.add_argument("--since", help="ISO 8601 timestamp")
    subscriptions_list.add_argument("--mode", help="Use 'extended' for additional metadata")
    subscriptions_list.set_defaults(handler=cmd_subscriptions_list)

    subscriptions_get = subscriptions_sub.add_parser("get", help="Get one subscription")
    subscriptions_get.add_argument("subscription_id", type=int)
    subscriptions_get.set_defaults(handler=cmd_subscriptions_get)

    subscriptions_add = subscriptions_sub.add_parser("add", help="Add a subscription")
    subscriptions_add.add_argument("--feed-url", required=True, help="Feed URL or site URL")
    subscriptions_add.set_defaults(handler=cmd_subscriptions_add)

    subscriptions_rename = subscriptions_sub.add_parser("rename", help="Rename a subscription")
    subscriptions_rename.add_argument("subscription_id", type=int)
    subscriptions_rename.add_argument("--title", required=True, help="Custom subscription title")
    subscriptions_rename.add_argument(
        "--use-post-update",
        action="store_true",
        help="Use POST /update.json instead of PATCH",
    )
    subscriptions_rename.set_defaults(handler=cmd_subscriptions_rename)

    subscriptions_remove = subscriptions_sub.add_parser("remove", help="Remove a subscription")
    subscriptions_remove.add_argument("subscription_id", type=int)
    subscriptions_remove.add_argument("--yes", action="store_true", help="Confirm destructive action")
    subscriptions_remove.set_defaults(handler=cmd_subscriptions_remove)

    pages = top.add_parser("pages", help="Saved page commands")
    pages_sub = pages.add_subparsers(dest="action", required=True)

    pages_save = pages_sub.add_parser("save", help="Save a URL as a Feedbin page")
    pages_save.add_argument("--url", required=True)
    pages_save.add_argument("--title", help="Optional fallback title")
    pages_save.set_defaults(handler=cmd_pages_save)

    pages_remove = pages_sub.add_parser("remove", help="Delete a saved page")
    pages_remove.add_argument("page_id", type=int)
    pages_remove.add_argument("--yes", action="store_true", help="Confirm destructive action")
    pages_remove.set_defaults(handler=cmd_pages_remove)

    taggings = top.add_parser("taggings", help="Tagging commands")
    taggings_sub = taggings.add_subparsers(dest="action", required=True)

    taggings_list = taggings_sub.add_parser("list", help="List taggings")
    taggings_list.set_defaults(handler=cmd_taggings_list)

    taggings_get = taggings_sub.add_parser("get", help="Get one tagging")
    taggings_get.add_argument("tagging_id", type=int)
    taggings_get.set_defaults(handler=cmd_taggings_get)

    taggings_add = taggings_sub.add_parser("add", help="Create a tagging")
    taggings_add.add_argument("--feed-id", type=int, required=True)
    taggings_add.add_argument("--name", required=True)
    taggings_add.set_defaults(handler=cmd_taggings_add)

    taggings_remove = taggings_sub.add_parser("remove", help="Delete a tagging")
    taggings_remove.add_argument("tagging_id", type=int)
    taggings_remove.add_argument("--yes", action="store_true", help="Confirm destructive action")
    taggings_remove.set_defaults(handler=cmd_taggings_remove)

    tags = top.add_parser("tags", help="Tag commands")
    tags_sub = tags.add_subparsers(dest="action", required=True)

    tags_rename = tags_sub.add_parser("rename", help="Rename a tag")
    tags_rename.add_argument("--old-name", required=True)
    tags_rename.add_argument("--new-name", required=True)
    tags_rename.set_defaults(handler=cmd_tags_rename)

    tags_delete = tags_sub.add_parser("delete", help="Delete a tag")
    tags_delete.add_argument("--name", required=True)
    tags_delete.add_argument("--yes", action="store_true", help="Confirm destructive action")
    tags_delete.set_defaults(handler=cmd_tags_delete)

    saved_searches = top.add_parser("saved-searches", help="Saved search commands")
    saved_sub = saved_searches.add_subparsers(dest="action", required=True)

    saved_list = saved_sub.add_parser("list", help="List saved searches")
    saved_list.set_defaults(handler=cmd_saved_searches_list)

    saved_get = saved_sub.add_parser("get", help="Get saved search results")
    saved_get.add_argument("saved_search_id", type=int)
    saved_get.add_argument("--include-entries", action="store_true", help="Return full entries")
    saved_get.add_argument("--page", type=int, help="Result page")
    saved_get.set_defaults(handler=cmd_saved_searches_get)

    saved_add = saved_sub.add_parser("add", help="Create a saved search")
    saved_add.add_argument("--name", required=True)
    saved_add.add_argument("--query", required=True)
    saved_add.set_defaults(handler=cmd_saved_searches_add)

    saved_update = saved_sub.add_parser("update", help="Update a saved search")
    saved_update.add_argument("saved_search_id", type=int)
    saved_update.add_argument("--name")
    saved_update.add_argument("--query")
    saved_update.add_argument(
        "--use-post-update",
        action="store_true",
        help="Use POST /update.json instead of PATCH",
    )
    saved_update.set_defaults(handler=cmd_saved_searches_update)

    saved_remove = saved_sub.add_parser("remove", help="Delete a saved search")
    saved_remove.add_argument("saved_search_id", type=int)
    saved_remove.add_argument("--yes", action="store_true", help="Confirm destructive action")
    saved_remove.set_defaults(handler=cmd_saved_searches_remove)

    archive = top.add_parser("archive", help="Download/archive entries into markdown and optional org-roam")
    archive_sub = archive.add_subparsers(dest="action", required=True)

    archive_pull = archive_sub.add_parser("pull", help="Download unread or starred entries and archive them")
    archive_pull.add_argument("--output", default=None, help="Directory to store downloaded markdown")
    archive_pull.add_argument("--blacklist", help="Optional blacklist file (feed IDs or feed titles)")
    archive_pull.add_argument("--ids", help="Comma-separated entry IDs to archive directly (bypasses unread/starred fetch)")
    archive_pull.add_argument("--max", type=int, default=None, help="Maximum entries to download (capped at 100)")
    archive_pull.add_argument(
        "--starred",
        action="store_true",
        default=None,
        help="Download starred entries instead of unread entries",
    )
    archive_pull.add_argument(
        "--unstar",
        action="store_true",
        default=None,
        help="Remove stars after successful archive pull (only with --starred)",
    )
    archive_pull.add_argument(
        "--org-roam",
        help="Path to org-roam directory. Enables org-roam note creation and attachment moves.",
    )
    archive_pull.add_argument(
        "--reading-index",
        help="Optional path to reading.org; appends new HOLD entries by org-roam ID.",
    )
    archive_pull.set_defaults(handler=cmd_archive_pull)

    archive_continue = archive_sub.add_parser(
        "continue-org-roam",
        help="Import existing markdown files from --output into org-roam without contacting Feedbin",
    )
    archive_continue.add_argument("--output", default="output", help="Directory containing markdown files")
    archive_continue.add_argument("--org-roam", required=True, help="Path to org-roam directory")
    archive_continue.add_argument("--reading-index", help="Optional path to reading.org")
    archive_continue.set_defaults(handler=cmd_archive_continue_org_roam)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if not args.no_auto_env:
            autoload_env()
        if args.env_file:
            load_env_file(args.env_file)

        config = read_config()
        client = FeedbinClient(config)
        handler = args.handler
        return int(handler(client, args))
    except CliError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
