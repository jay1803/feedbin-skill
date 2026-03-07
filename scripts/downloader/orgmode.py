"""Org-roam integration for feedbin archive workflows."""

from __future__ import annotations

import datetime as dt
import errno
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable

from .content import slugify


def generate_uuid() -> str:
    return str(uuid.uuid4())


def get_timestamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d%H%M%S")


def create_org_filename(title: str) -> str:
    return f"{get_timestamp()}-{slugify(title, 'article')}.org"


def create_attachment_path(org_roam_dir: Path, file_uuid: str) -> Path:
    uuid_clean = file_uuid.replace("-", "")
    first_two = uuid_clean[:2]
    rest = uuid_clean[2:]
    rest_with_dashes = f"{rest[:6]}-{rest[6:10]}-{rest[10:14]}-{rest[14:18]}-{rest[18:]}"
    return org_roam_dir / "data" / first_two / rest_with_dashes


def create_org_content(title: str, url: str, file_uuid: str, entry_id: int | None = None) -> str:
    refs: list[str] = []
    if url:
        refs.append(url)
    if entry_id is not None:
        refs.append(f"https://feedbin.com/entries/{entry_id}")
    roam_refs = " ".join(refs)

    return "\n".join(
        [
            ":PROPERTIES:",
            f":ID:       {file_uuid}",
            f":ROAM_REFS: {roam_refs}",
            ":END:",
            f"#+title: {title}",
            "#+filetags: :ref:",
            "",
        ]
    )


def get_existing_urls(org_roam_dir: Path) -> set[str]:
    existing_urls: set[str] = set()
    for org_file in org_roam_dir.glob("*.org"):
        try:
            content = org_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in content.splitlines():
            if line.startswith(":ROAM_REFS:"):
                refs_value = line.split(":", 2)[-1].strip()
                if refs_value:
                    for ref in refs_value.split():
                        existing_urls.add(ref)
                break
    return existing_urls


def add_to_reading_index(entry_uuid: str, title: str, reading_file: Path, log: Callable[[str], None]) -> None:
    if not reading_file.exists():
        log(f"Reading index file not found: {reading_file}")
        return

    index_entry = f"** HOLD [[id:{entry_uuid}][{title}]]"
    try:
        content = reading_file.read_text(encoding="utf-8")
        if f"id:{entry_uuid}" in content:
            return
        if not content.endswith("\n"):
            content += "\n"
        content += index_entry + "\n"
        reading_file.write_text(content, encoding="utf-8")
        log(f"Added to reading index: {title}")
    except OSError as exc:
        log(f"Failed to update reading index: {exc}")


def ensure_dir_with_retry(path: Path, retries: int = 4, base_delay: float = 0.6) -> None:
    last_err: Exception | None = None
    for i in range(retries):
        try:
            path.mkdir(parents=True, exist_ok=True)
            return
        except OSError as exc:
            last_err = exc
            deadlock_like = exc.errno in {errno.EDEADLK, errno.EBUSY, errno.EAGAIN, 11}
            if i < retries - 1 and deadlock_like:
                time.sleep(base_delay * (2**i))
                continue
            break
    if last_err:
        raise last_err


def _copy_unlink_move(src: Path, dst: Path) -> None:
    shutil.copy2(src, dst)
    try:
        with dst.open("rb") as fh:
            os.fsync(fh.fileno())
    except OSError:
        pass
    src.unlink()


def move_with_retry(src: Path, dst: Path, retries: int = 3, base_delay: float = 0.6) -> None:
    last_err: Exception | None = None
    for i in range(retries):
        try:
            shutil.move(str(src), str(dst))
            return
        except OSError as exc:
            last_err = exc
            deadlock_like = exc.errno in {errno.EDEADLK, errno.EBUSY, errno.EAGAIN, 11}
            if deadlock_like:
                try:
                    _copy_unlink_move(src, dst)
                    return
                except Exception as inner:
                    last_err = inner
            if i < retries - 1:
                time.sleep(base_delay * (2**i))
    if last_err:
        raise last_err


def move_markdown_to_attachment(markdown_file: Path, org_roam_dir: Path, file_uuid: str, log: Callable[[str], None]) -> Path:
    attachment_dir = create_attachment_path(org_roam_dir, file_uuid)
    ensure_dir_with_retry(attachment_dir)
    attachment_file = attachment_dir / markdown_file.name
    move_with_retry(markdown_file, attachment_file)
    log(f"Moved {markdown_file} -> {attachment_file}")
    return attachment_file


def extract_markdown_metadata(markdown_file: Path, log: Callable[[str], None]) -> dict[str, str] | None:
    try:
        content = markdown_file.read_text(encoding="utf-8")
    except OSError as exc:
        log(f"Failed to read markdown file {markdown_file}: {exc}")
        return None

    title = ""
    feed_title = ""
    url = ""

    for line in content.splitlines():
        if not title and line.startswith("# "):
            title = line[2:].strip()
            continue
        if line.startswith("*Source:*"):
            feed_title = line[len("*Source:*") :].strip()
            continue
        if line.startswith("*URL:*"):
            url = line[len("*URL:*") :].strip()

    return {
        "title": title or markdown_file.stem,
        "feed_title": feed_title or markdown_file.parent.name,
        "url": url,
    }


def continue_orgmode_import(
    output_dir: Path,
    org_roam_dir: Path,
    reading_index_file: Path | None,
    *,
    log: Callable[[str], None],
) -> list[Path]:
    if not output_dir.is_dir():
        log(f"Output directory not found: {output_dir}")
        return []

    processed_files: list[Path] = []
    existing_urls = get_existing_urls(org_roam_dir)
    log(f"Found {len(existing_urls)} existing articles in org-roam")

    for markdown_file in sorted(output_dir.rglob("*.md")):
        metadata = extract_markdown_metadata(markdown_file, log)
        if metadata is None:
            continue

        title = metadata["title"]
        url = metadata["url"]

        if url and url in existing_urls:
            log(f"Skipping duplicate article: {title} ({url})")
            continue

        file_uuid = generate_uuid()
        org_file_path = org_roam_dir / create_org_filename(title)
        attachment_file = None

        try:
            attachment_file = move_markdown_to_attachment(markdown_file, org_roam_dir, file_uuid, log)
            org_file_path.write_text(create_org_content(title, url, file_uuid), encoding="utf-8")
            log(f"Created org-roam file: {org_file_path}")

            if reading_index_file:
                add_to_reading_index(file_uuid, title, reading_index_file, log)

            if url:
                existing_urls.add(url)
            processed_files.append(markdown_file)
        except Exception as exc:
            log(f"Failed to continue org-roam import for {markdown_file}: {exc}")
            if attachment_file is not None:
                try:
                    move_with_retry(attachment_file, markdown_file)
                except Exception:
                    pass

    return processed_files


def integrate_with_orgmode(
    entries: list[dict],
    feeds: dict[int, dict],
    markdown_files: dict[int, Path | None],
    org_roam_dir: Path,
    reading_index_file: Path | None,
    *,
    log: Callable[[str], None],
) -> list[int]:
    processed_ids: list[int] = []
    existing_urls = get_existing_urls(org_roam_dir)
    log(f"Found {len(existing_urls)} existing articles in org-roam")

    for entry in entries:
        entry_id = entry.get("id")
        if not isinstance(entry_id, int) or entry_id not in markdown_files:
            continue

        markdown_file = markdown_files[entry_id]
        title = str(entry.get("title") or f"Entry {entry_id}")
        url = str(entry.get("url") or "")

        if url and url in existing_urls:
            log(f"Skipping duplicate article: {title} ({url})")
            continue

        file_uuid = generate_uuid()
        org_file_path = org_roam_dir / create_org_filename(title)
        attachment_file = None

        if markdown_file is not None:
            if not markdown_file.exists():
                log(f"Markdown file not found for entry {entry_id}: {markdown_file}")
                continue
            try:
                attachment_file = move_markdown_to_attachment(markdown_file, org_roam_dir, file_uuid, log)
            except Exception as exc:
                log(f"Failed to move markdown file for entry {entry_id}: {exc}")
                continue
        else:
            log(f"Creating ref-only org-roam entry for video URL: {title}")

        try:
            org_file_path.write_text(create_org_content(title, url, file_uuid, entry_id), encoding="utf-8")
            log(f"Created org-roam file: {org_file_path}")

            if reading_index_file:
                add_to_reading_index(file_uuid, title, reading_index_file, log)

            if url:
                existing_urls.add(url)
            processed_ids.append(entry_id)
        except Exception as exc:
            log(f"Failed to create org file for entry {entry_id}: {exc}")
            if attachment_file is not None and markdown_file is not None:
                try:
                    move_with_retry(attachment_file, markdown_file)
                except Exception:
                    pass

    return processed_ids
