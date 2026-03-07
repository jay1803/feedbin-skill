"""File storage operations and blacklist handling."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .content import build_article_content, extract_audio_url, is_video_url, slugify


def read_blacklist(path: Path | None) -> tuple[set[int], set[str]]:
    ids: set[int] = set()
    titles: set[str] = set()
    if not path:
        return ids, titles
    if not path.is_file():
        raise FileNotFoundError(f"Blacklist file not found: {path}")

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.isdigit():
            ids.add(int(line))
        else:
            titles.add(line.lower())
    return ids, titles


def ensure_unique_path(directory: Path, base_name: str) -> Path:
    candidate = base_name
    counter = 1
    target = directory / f"{candidate}.md"
    while target.exists():
        counter += 1
        candidate = f"{base_name}-{counter}"
        target = directory / f"{candidate}.md"
    return target


def ensure_unique_file_path(directory: Path, base_name: str, extension: str) -> Path:
    ext = extension if extension.startswith(".") else f".{extension}"
    candidate = base_name
    counter = 1
    target = directory / f"{candidate}{ext}"
    while target.exists():
        counter += 1
        candidate = f"{base_name}-{counter}"
        target = directory / f"{candidate}{ext}"
    return target


def process_entries(
    entries: list[dict],
    feeds: dict[int, dict],
    output_dir: Path,
    blacklist_ids: set[int],
    blacklist_titles: set[str],
    *,
    fetch_extracted: Callable[[str], str | None] | None = None,
    download_binary: Callable[[str], bytes | None] | None = None,
    log: Callable[[str], None],
    video_ref_only: bool = False,
) -> tuple[list[int], dict[int, Path | None]]:
    processed: list[int] = []
    entry_files: dict[int, Path | None] = {}

    for entry in entries:
        entry_id = entry.get("id")
        if not isinstance(entry_id, int):
            continue

        feed_id = entry.get("feed_id")
        feed = feeds.get(feed_id, {}) if isinstance(feed_id, int) else {}
        feed_title = feed.get("title") or (f"Feed {feed_id}" if isinstance(feed_id, int) else "Unknown Feed")

        if isinstance(feed_id, int) and feed_id in blacklist_ids:
            log(f"Skipping entry {entry_id} from feed ID {feed_id} (blacklisted)")
            continue
        if str(feed_title).lower() in blacklist_titles:
            log(f"Skipping entry {entry_id} from feed '{feed_title}' (blacklisted)")
            continue

        url = str(entry.get("url") or "")
        if video_ref_only and is_video_url(url):
            log(f"Skipping markdown download for video entry {entry_id}: {url}")
            processed.append(entry_id)
            entry_files[entry_id] = None
            continue

        directory = output_dir / slugify(str(feed_title), f"feed-{feed_id or 'unknown'}")
        directory.mkdir(parents=True, exist_ok=True)

        title = str(entry.get("title") or f"Entry {entry_id}")
        base_name = slugify(title, f"entry-{entry_id}")

        audio_url = extract_audio_url(entry)
        if audio_url:
            existing_audio = list(directory.glob(f"{base_name}*.mp3"))
            if existing_audio:
                log(f"Using existing podcast file for entry {entry_id}: {existing_audio[0]}")
                processed.append(entry_id)
                entry_files[entry_id] = existing_audio[0]
                continue

            if download_binary is None:
                log(f"Skipping podcast entry {entry_id}; no binary downloader available: {audio_url}")
                continue

            audio_bytes = download_binary(audio_url)
            if not audio_bytes:
                log(f"Failed to download podcast audio for entry {entry_id}: {audio_url}")
                continue

            audio_target = ensure_unique_file_path(directory, base_name, ".mp3")
            audio_target.write_bytes(audio_bytes)
            log(f"Saved podcast entry {entry_id} -> {audio_target}")
            processed.append(entry_id)
            entry_files[entry_id] = audio_target
            continue

        existing = list(directory.glob(f"{base_name}*.md"))
        if existing:
            target_path = existing[0]
            log(f"Using existing file for entry {entry_id}: {target_path}")
            processed.append(entry_id)
            entry_files[entry_id] = target_path
            continue

        target_path = ensure_unique_path(directory, base_name)

        extracted_content = None
        extracted_url = entry.get("extracted_content_url")
        if fetch_extracted and isinstance(extracted_url, str) and extracted_url:
            extracted_content = fetch_extracted(extracted_url)
            if extracted_content:
                log(f"Using extracted content for entry {entry_id}")

        document = build_article_content(entry, feed, extracted_content)
        target_path.write_text(document, encoding="utf-8")
        log(f"Saved entry {entry_id} -> {target_path}")

        processed.append(entry_id)
        entry_files[entry_id] = target_path

    return processed, entry_files
