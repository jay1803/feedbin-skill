"""Content processing and HTML-to-Markdown conversion."""

from __future__ import annotations

import datetime as dt
import html
import re
import shutil
import subprocess
import unicodedata
from urllib.parse import urlparse

VIDEO_HOSTS = {
    "youtube.com",
    "m.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
}


def is_video_url(url: str) -> bool:
    if not url:
        return False
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname in VIDEO_HOSTS


def slugify(value: str, fallback: str, max_length: int = 80) -> str:
    value = value or ""
    normalized = unicodedata.normalize("NFKC", value)
    cleaned = re.sub(r"[\t\n\r]+", " ", normalized)
    cleaned = re.sub(r'[<>:"/\\|?*]', "-", cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    cleaned = cleaned.strip("-._")

    if len(cleaned) > max_length:
        truncated = cleaned[:max_length]
        last_hyphen = truncated.rfind("-")
        if last_hyphen > max_length // 2:
            cleaned = truncated[:last_hyphen]
        else:
            cleaned = truncated

    return cleaned if cleaned else fallback


def strip_tags(raw_html: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", "", raw_html)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return html.unescape(cleaned)


def fallback_markdown(html_content: str) -> str:
    text = html_content or ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", "", text)
    text = re.sub(r"(?i)<br\\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(
        r"(?is)<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>",
        lambda m: (strip_tags(m.group(2)) + f" ({m.group(1)})") if strip_tags(m.group(2)) else m.group(1),
        text,
    )
    text = re.sub(r"(?is)<li[^>]*>", "\n- ", text)
    text = re.sub(r"(?is)</(ul|ol)>", "\n", text)
    text = re.sub(r"(?is)<blockquote[^>]*>", "\n> ", text)
    text = re.sub(r"(?is)</blockquote>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [line.rstrip() for line in text.splitlines()]

    compact: list[str] = []
    blank = True
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if not blank:
                compact.append("")
            blank = True
        else:
            compact.append(stripped)
            blank = False
    return "\n".join(compact).strip()


def html_to_markdown(html_content: str) -> str:
    if not html_content:
        return ""
    pandoc = shutil.which("pandoc")
    if pandoc:
        try:
            result = subprocess.run(
                [pandoc, "--from=html", "--to=gfm"],
                input=html_content,
                text=True,
                capture_output=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            pass
    return fallback_markdown(html_content)


def format_timestamp(raw_value: str) -> str:
    try:
        parsed = dt.datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return raw_value
    return parsed.strftime("%Y-%m-%d %H:%M:%S %z").strip()


def build_article_content(entry: dict, feed: dict, extracted_content: str | None = None) -> str:
    title = entry.get("title") or f"Entry {entry.get('id')}"
    feed_title = feed.get("title") or f"Feed {entry.get('feed_id') or 'unknown'}"

    html_body = extracted_content or entry.get("content") or entry.get("summary") or ""
    markdown_body = html_to_markdown(html_body)

    header_lines = [f"# {title}", "", f"*Source:* {feed_title}"]
    url = entry.get("url") or ""
    if url:
        header_lines.append(f"*URL:* {url}")
    feed_url = feed.get("feed_url") if isinstance(feed, dict) else ""
    if not url and feed_url:
        header_lines.append(f"*Feed URL:* {feed_url}")

    published = entry.get("published") or entry.get("created_at")
    if published:
        header_lines.append(f"*Published:* {format_timestamp(published)}")

    sections = ["\n".join(header_lines).strip()]
    if markdown_body:
        sections.append("")
        sections.append(markdown_body)
    return "\n".join(sections).strip() + "\n"
