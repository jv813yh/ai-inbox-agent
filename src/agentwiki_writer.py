#!/usr/bin/env python3
"""Write ai-inbox-agent outputs as HumanAgentWiki/Obsidian Markdown notes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, *, fallback: str = "untitled", max_length: int = 90) -> str:
    """Return a safe, readable filename slug."""
    value = value.lower().replace("/", " ").replace("\\", " ")
    value = _SLUG_RE.sub("-", value).strip("-")
    if not value:
        value = fallback
    return value[:max_length].strip("-") or fallback


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split())
    if re.fullmatch(r"[A-Za-z0-9 _./:+-]+", text) and ": " not in text:
        return text
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _frontmatter(fields: Mapping[str, Any]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list):
            lines.append(f"{key}: [" + ", ".join(_yaml_scalar(v) for v in value) + "]")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


class AgentWikiWriter:
    """Safe writer for HumanAgentWiki Markdown notes and index notes."""

    def __init__(self, notes_dir: str | Path):
        self.notes_dir = Path(notes_dir).expanduser().resolve()
        self.notes_dir.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, rel_path: str | Path) -> Path:
        rel = Path(rel_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"Unsafe relative path: {rel_path}")
        path = (self.notes_dir / rel).resolve()
        if self.notes_dir not in path.parents and path != self.notes_dir:
            raise ValueError(f"Path escapes notes dir: {rel_path}")
        return path

    def _write_note(self, rel_path: str, content: str) -> str:
        path = self._safe_path(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        return path.relative_to(self.notes_dir).as_posix()

    @staticmethod
    def _email_source(email_meta: Mapping[str, Any]) -> str:
        return (
            f"From: {email_meta.get('from', 'Unknown')}\n"
            f"Subject: {email_meta.get('subject', '')}\n"
            f"Date: {email_meta.get('date', '')}\n"
            f"Message-ID: {email_meta.get('message_id', '')}"
        )

    def write_youtube_note(
        self,
        item: Mapping[str, Any],
        *,
        email_meta: Mapping[str, Any],
        gmail_account: str,
    ) -> str:
        title = str(item.get("title") or item.get("url") or "YouTube Video")
        video_id = str(item.get("video_id") or self._video_id_from_url(str(item.get("url", ""))) or slugify(title))
        date_prefix = str(item.get("processed_at", ""))[:10] or "undated"
        rel_path = f"Videos/{date_prefix}--{slugify(video_id)}--{slugify(title)}.md"

        front = _frontmatter(
            {
                "title": title,
                "category": "Videos",
                "type": "youtube_video",
                "tags": ["youtube", "video", "ai-inbox", "learning-gmail"],
                "source_url": item.get("url", ""),
                "video_id": video_id,
                "channel": item.get("channel", ""),
                "gmail_account": gmail_account,
                "gmail_message_id": email_meta.get("message_id", ""),
                "processed_at": item.get("processed_at", ""),
                "transcript_available": bool(item.get("has_full_transcript")),
            }
        )
        body = f"""# {title}

Source: {item.get('url', '')}

Email source:
{self._email_source(email_meta)}

## Summary
{item.get('summary', '').strip()}

## My take
{item.get('my_take', '').strip()}

## Key metadata
- Channel: {item.get('channel', '')}
- Transcript available: {'yes' if item.get('has_full_transcript') else 'no'}

## Transcript preview
{item.get('transcript_preview', '').strip()}

## Related
- [[YouTube Video Index]]
- [[Learning Gmail Inbox]]
"""
        return self._write_note(rel_path, front + "\n\n" + body)

    def write_github_note(
        self,
        item: Mapping[str, Any],
        *,
        email_meta: Mapping[str, Any],
        gmail_account: str,
    ) -> str:
        owner = str(item.get("owner") or "unknown")
        repo = str(item.get("repo") or "unknown")
        name = f"{owner}/{repo}"
        rel_path = f"GitHub Projects/{slugify(owner)}--{slugify(repo)}.md"

        front = _frontmatter(
            {
                "title": name,
                "category": "GitHub Projects",
                "type": "github_project",
                "tags": ["github", "project", "ai-inbox", "learning-gmail"],
                "source_url": item.get("url", ""),
                "owner": owner,
                "repo": repo,
                "language": item.get("language", ""),
                "stars": item.get("stars", 0),
                "forks": item.get("forks", 0),
                "gmail_account": gmail_account,
                "gmail_message_id": email_meta.get("message_id", ""),
                "processed_at": item.get("processed_at", ""),
            }
        )
        topics = ", ".join(str(t) for t in item.get("topics", []) or [])
        body = f"""# {name}

Source: {item.get('url', '')}

Email source:
{self._email_source(email_meta)}

## What it is
{item.get('summary', '').strip()}

## My take
{item.get('my_take', '').strip()}

## Practical value for Jozef
- Review for AI agents / backend / automation ideas.

## Repo metadata
- Stars: {item.get('stars', 0)}
- Forks: {item.get('forks', 0)}
- Language: {item.get('language', '')}
- Topics: {topics}

## README preview
{item.get('readme_preview', '').strip()}

## Related
- [[GitHub Project Index]]
- [[Learning Gmail Inbox]]
"""
        return self._write_note(rel_path, front + "\n\n" + body)

    def upsert_youtube_index(self, item: Mapping[str, Any], rel_note_path: str) -> str:
        title = str(item.get("title") or item.get("url") or "YouTube Video")
        entry = f"- [[{title}]] — {item.get('channel', 'Unknown')} — {item.get('url', '')} — `{rel_note_path}`"
        return self._upsert_index("Indexes/youtube-video-index.md", "YouTube Video Index", ["index", "youtube", "ai-inbox"], entry)

    def upsert_github_index(self, item: Mapping[str, Any], rel_note_path: str) -> str:
        name = f"{item.get('owner', 'unknown')}/{item.get('repo', 'unknown')}"
        entry = f"- [[{name}]] — {item.get('language', 'Unknown')} / ⭐{item.get('stars', 0)} — {item.get('url', '')} — `{rel_note_path}`"
        return self._upsert_index("Indexes/github-project-index.md", "GitHub Project Index", ["index", "github", "ai-inbox"], entry)

    def _upsert_index(self, rel_path: str, title: str, tags: list[str], entry: str) -> str:
        path = self._safe_path(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            text = path.read_text(encoding="utf-8").rstrip()
            lines = text.splitlines()
            # Drop older entry for same note link/title-like key to keep idempotent.
            key = entry.split(" — ", 1)[0]
            lines = [line for line in lines if not line.startswith(key)]
            text = "\n".join(lines).rstrip() + "\n" + entry + "\n"
        else:
            front = _frontmatter({"title": title, "category": "Indexes", "type": "index", "tags": tags})
            text = f"{front}\n\n# {title}\n\n{entry}\n"
        path.write_text(text, encoding="utf-8")
        return path.relative_to(self.notes_dir).as_posix()

    @staticmethod
    def _video_id_from_url(url: str) -> str:
        match = re.search(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})", url)
        return match.group(1) if match else ""
