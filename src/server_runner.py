#!/usr/bin/env python3
"""Server-local runner: learning Gmail -> summaries -> HumanAgentWiki notes.

This entrypoint is intended for Hermes cron on Jozef's server. It uses Gmail API
OAuth tokens, writes Markdown files to HumanAgentWiki, indexes the notes, prints a
Telegram-ready digest to stdout, and marks Gmail messages as read only after
successful processing.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse

try:  # package import when tested as `src.server_runner`
    from .agentwiki_writer import AgentWikiWriter
    from .content_classifier import classify_article_item, classify_plain_email_item, classify_youtube_item
    from .gmail_api_client import GmailApiClient, GmailMessage
    from .state_store import StateStore
except ImportError:  # script execution as `python src/server_runner.py`
    from agentwiki_writer import AgentWikiWriter
    from content_classifier import classify_article_item, classify_plain_email_item, classify_youtube_item
    from gmail_api_client import GmailMessage, GmailApiClient
    from state_store import StateStore


DEFAULT_QUERY = "in:inbox is:unread newer_than:30d"
DEFAULT_TOKEN_PATH = "/home/jozef/.hermes/google_accounts/learning/google_token.json"
DEFAULT_NOTES_DIR = "/home/jozef/humanagentwiki/notes"
DEFAULT_HAW_DIR = "/home/jozef/humanagentwiki"
DEFAULT_STATE_DB = "/home/jozef/.hermes/state/ai-inbox-agent/processed.sqlite"

_YOUTUBE_RE = re.compile(r"https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?[^\s<>'\"]+|embed/[A-Za-z0-9_-]{11}|shorts/[A-Za-z0-9_-]{11})|youtu\.be/[A-Za-z0-9_-]{11}[^\s<>'\"]*)")
_GITHUB_RE = re.compile(r"https?://(?:www\.)?github\.com/([^/\s]+)/([^/\s?#.,;:!]+)(?:/[^\s<>'\"]*)?")
_GENERIC_URL_RE = re.compile(r"https?://[^\s<>'\"\]]+[^\s<>'\"\].,;:!?)]")
_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})")
_ARTICLE_SKIP_RE = re.compile(
    r"(youtube\.com|youtu\.be|github\.com|githubusercontent\.com|gist\.github\.com|codeload\.github\.com|mail\.google\.com|accounts\.google\.com|"
    r"unsubscribe|privacy-policy|terms-of-service|list-manage\.com|"
    r"\.(jpg|jpeg|png|gif|svg|ico|css|js|woff|woff2)([?#]|$))",
    re.IGNORECASE,
)
_TRACKING_QUERY_PREFIXES = ("utm_", "mc_")
_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "ref", "ref_src", "igshid"}
MIN_PLAIN_EMAIL_CHARS = 150
_NO_CHECK_SUBJECT_RE = re.compile(r"\bno\s*check\b", re.IGNORECASE)


@dataclass(frozen=True)
class ClassifiedLinks:
    youtube: list[str] = field(default_factory=list)
    github: list[str] = field(default_factory=list)
    articles: list[str] = field(default_factory=list)


def _clean_url(url: str) -> str:
    return url.rstrip(".,;:!?)\n\r\t ")


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _dedupe_by(values: Iterable[str], key_fn) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = key_fn(value)
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def classify_links(text: str) -> ClassifiedLinks:
    """Extract YouTube, GitHub repo, and generic web article links from email text."""
    youtube = _dedupe(_clean_url(m.group(0)) for m in _YOUTUBE_RE.finditer(text or ""))
    github = _dedupe(
        f"https://github.com/{m.group(1)}/{m.group(2)}" for m in _GITHUB_RE.finditer(text or "")
    )
    articles = _dedupe(
        _clean_url(m.group(0))
        for m in _GENERIC_URL_RE.finditer(text or "")
        if not _ARTICLE_SKIP_RE.search(m.group(0))
    )
    return ClassifiedLinks(youtube=youtube, github=github, articles=articles)


def source_id_for_youtube_url(url: str) -> str:
    match = _VIDEO_ID_RE.search(url or "")
    return match.group(1) if match else _clean_url(url)


def source_id_for_github_url(url: str) -> str:
    match = _GITHUB_RE.search(url or "")
    if not match:
        return _clean_url(url)
    return f"{match.group(1)}/{match.group(2)}"


def source_id_for_article_url(url: str) -> str:
    parsed = urlparse(_clean_url(url))
    kept = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lower = key.lower()
        if lower in _TRACKING_QUERY_KEYS or lower.startswith(_TRACKING_QUERY_PREFIXES):
            continue
        kept.append((key, value))
    return parsed._replace(fragment="", query=urlencode(kept, doseq=True)).geturl()


def _lazy_content_preparator():
    # Heavy imports (anthropic, bs4, yt-dlp) happen only during real processing.
    try:
        from .extractors_full import ContentPreparator
    except ImportError:
        from extractors_full import ContentPreparator
    return ContentPreparator


def subject_requests_no_check(subject: str) -> bool:
    """Return True when an email subject explicitly asks to bypass source dedupe.

    Jozef can resend a previously processed link with `no check` in the subject
    to force reprocessing without deleting state rows.
    """
    return bool(_NO_CHECK_SUBJECT_RE.search(subject or ""))


def process_messages(
    messages: list[GmailMessage],
    *,
    notes_dir: str | Path,
    state_db: str | Path,
    gmail_account: str = "learning",
    dry_run: bool = False,
    include_plain_emails: bool = False,
) -> tuple[str, list[str]]:
    """Process fetched Gmail messages.

    Returns `(digest, successful_message_ids)`. In dry-run mode no notes/state are
    written and no messages should be marked read by the caller.
    """
    store = None if dry_run else StateStore(state_db)
    writer = None if dry_run else AgentWikiWriter(notes_dir)
    successful_message_ids: list[str] = []
    digest_lines: list[str] = []

    if not messages:
        return "", []

    ContentPreparator = None

    for msg in messages:
        bypass_duplicate_check = subject_requests_no_check(msg.subject)
        if store and not bypass_duplicate_check:
            existing_status = store.get_message_status(gmail_account, msg.id)
            if existing_status:
                digest_lines.append(f"⏭️ Already handled email ({existing_status}): {msg.subject or msg.id}")
                successful_message_ids.append(msg.id)
                continue

        email_text = "\n".join([msg.subject, msg.body, msg.snippet])
        links = classify_links(email_text)
        has_links = bool(links.youtube or links.github or links.articles)
        plain_candidate = include_plain_emails and len((msg.body or "").strip()) >= MIN_PLAIN_EMAIL_CHARS
        unclassified_candidate = not has_links and not plain_candidate

        if dry_run:
            digest_lines.append(
                f"DRY RUN: {msg.subject or msg.id} — YouTube {len(links.youtube)}, GitHub {len(links.github)}, Articles {len(links.articles)}, PlainEmail {1 if plain_candidate and not has_links else 0}, Unclassified {1 if unclassified_candidate else 0}"
            )
            continue

        if unclassified_candidate:
            assert store is not None
            store.record_message(
                gmail_account=gmail_account,
                gmail_message_id=msg.id,
                thread_id=msg.thread_id,
                subject=msg.subject,
                from_addr=msg.from_addr,
                status="skipped_unclassified",
            )
            digest_lines.append(f"⏭️ Skipped unclassified short/no-link email: {msg.subject or msg.id}")
            successful_message_ids.append(msg.id)
            continue

        assert store is not None
        assert writer is not None

        wrote_anything = False

        if bypass_duplicate_check:
            youtube_urls = _dedupe_by(links.youtube, source_id_for_youtube_url)
            github_urls = _dedupe_by(links.github, source_id_for_github_url)
            article_urls = _dedupe_by(links.articles, source_id_for_article_url)
        else:
            youtube_urls = _dedupe_by(
                (u for u in links.youtube if not store.is_source_processed("youtube", source_id_for_youtube_url(u))),
                source_id_for_youtube_url,
            )
            github_urls = [u for u in links.github if not store.is_source_processed("github", source_id_for_github_url(u))]
            article_urls = _dedupe_by(
                (u for u in links.articles if not store.is_source_processed("article", source_id_for_article_url(u))),
                source_id_for_article_url,
            )

        if has_links and not youtube_urls and not github_urls and not article_urls:
            store.record_message(
                gmail_account=gmail_account,
                gmail_message_id=msg.id,
                thread_id=msg.thread_id,
                subject=msg.subject,
                from_addr=msg.from_addr,
                status="skipped_duplicate",
            )
            digest_lines.append(f"⏭️ Skipped duplicate email: {msg.subject or msg.id}")
            successful_message_ids.append(msg.id)
            continue

        if ContentPreparator is None:
            ContentPreparator = _lazy_content_preparator()

        if youtube_urls:
            youtube_items = ContentPreparator.prepare_youtube_batch(youtube_urls, email_body=msg.body)
            for item in youtube_items:
                item.setdefault("video_id", source_id_for_youtube_url(str(item.get("url", ""))))
                item.setdefault("classification", classify_youtube_item(item, email_text=email_text))
                rel_path = writer.write_youtube_note(item, email_meta=msg.email_meta, gmail_account=gmail_account)
                writer.upsert_youtube_index(item, rel_path)
                learning_rel = writer.write_learning_note_if_useful(
                    item,
                    source_rel_path=rel_path,
                    source_type="youtube_video",
                    gmail_account=gmail_account,
                )
                if learning_rel:
                    writer.upsert_learning_index(item, learning_rel, rel_path)
                store.record_source(
                    source_type="youtube",
                    source_id=str(item.get("video_id") or source_id_for_youtube_url(str(item.get("url", "")))),
                    source_url=str(item.get("url", "")),
                    note_path=rel_path,
                    first_seen_message_id=msg.id,
                )
                channel = item.get('channel') or (item.get('classification') or {}).get('channel_name') or 'Unknown Channel'
                digest_lines.append(f"🎥 {item.get('title', 'YouTube video')} — {channel} → {rel_path}")
                if learning_rel:
                    digest_lines.append(f"🧠 Learning → {learning_rel}")
                wrote_anything = True

        if github_urls:
            github_items = ContentPreparator.prepare_github_batch(github_urls)
            for item in github_items:
                rel_path = writer.write_github_note(item, email_meta=msg.email_meta, gmail_account=gmail_account)
                writer.upsert_github_index(item, rel_path)
                store.record_source(
                    source_type="github",
                    source_id=f"{item.get('owner', '')}/{item.get('repo', '')}",
                    source_url=str(item.get("url", "")),
                    note_path=rel_path,
                    first_seen_message_id=msg.id,
                )
                desc = str(item.get('description') or '').strip()
                desc_suffix = f" — {desc[:120]}" if desc else ""
                digest_lines.append(f"🐙 {item.get('owner', '')}/{item.get('repo', '')}{desc_suffix} → {rel_path}")
                wrote_anything = True

        if article_urls:
            article_items = ContentPreparator.prepare_article_batch(article_urls)
            for item in article_items:
                item.setdefault("classification", classify_article_item(item, email_text=email_text))
                rel_path = writer.write_article_note(item, email_meta=msg.email_meta, gmail_account=gmail_account)
                writer.upsert_article_index(item, rel_path)
                learning_rel = writer.write_learning_note_if_useful(
                    item,
                    source_rel_path=rel_path,
                    source_type="web_article",
                    gmail_account=gmail_account,
                )
                if learning_rel:
                    writer.upsert_learning_index(item, learning_rel, rel_path)
                store.record_source(
                    source_type="article",
                    source_id=source_id_for_article_url(str(item.get("url", ""))),
                    source_url=str(item.get("url", "")),
                    note_path=rel_path,
                    first_seen_message_id=msg.id,
                )
                digest_lines.append(f"📰 {item.get('title', 'Web article')} → {rel_path}")
                if learning_rel:
                    digest_lines.append(f"🧠 Learning → {learning_rel}")
                wrote_anything = True

        if plain_candidate and not has_links:
            item = ContentPreparator.prepare_plain_email(msg.subject, msg.from_addr, msg.body)
            if item:
                item.setdefault("classification", classify_plain_email_item(item, email_text=email_text))
                rel_path = writer.write_plain_email_note(item, email_meta=msg.email_meta, gmail_account=gmail_account)
                writer.upsert_plain_email_index(item, rel_path)
                digest_lines.append(f"✉️ {item.get('subject', msg.subject or 'Email')} → {rel_path}")
                wrote_anything = True

        failed_processing = (has_links or plain_candidate) and not wrote_anything
        if wrote_anything:
            store.record_message(
                gmail_account=gmail_account,
                gmail_message_id=msg.id,
                thread_id=msg.thread_id,
                subject=msg.subject,
                from_addr=msg.from_addr,
                status="processed",
            )
            successful_message_ids.append(msg.id)
        elif failed_processing:
            store.record_message(
                gmail_account=gmail_account,
                gmail_message_id=msg.id,
                thread_id=msg.thread_id,
                subject=msg.subject,
                from_addr=msg.from_addr,
                status="skipped_failed_processing",
            )
            digest_lines.append(f"⚠️ Failed processing links in email: {msg.subject or msg.id}")
            successful_message_ids.append(msg.id)

    return "\n".join(digest_lines).strip(), successful_message_ids


def load_env_file(path: str | Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file without printing or exporting secrets."""
    env_path = Path(path).expanduser()
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def index_humanagentwiki(humanagentwiki_dir: str | Path, notes_dir: str | Path, *, dry_run: bool = False) -> tuple[bool, str]:
    if dry_run:
        return True, "dry-run"
    haw_dir = Path(humanagentwiki_dir).expanduser()
    python_bin = haw_dir / ".venv" / "bin" / "python"
    cmd = [str(python_bin if python_bin.exists() else "python3"), "cli.py", "index"]
    env = os.environ.copy()
    env.update(load_env_file(haw_dir / ".env"))
    env["NOTES_DIR"] = str(Path(notes_dir).expanduser())
    try:
        subprocess.run(cmd, cwd=haw_dir, env=env, check=True, timeout=600)
        return True, "indexed"
    except subprocess.CalledProcessError as exc:
        return False, f"HumanAgentWiki index failed with exit {exc.returncode}; note files are saved and indexing is queued for later"
    except Exception as exc:
        return False, f"HumanAgentWiki index failed: {exc}; note files are saved and indexing is queued for later"


def _extract_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    values: dict[str, str] = {}
    for raw in text[4:end].splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        value = value.strip().strip('"')
        if key.strip():
            values[key.strip()] = value
    return values


def _extract_markdown_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text or "")
    if not match:
        return ""
    next_heading = re.search(r"^##\s+", text[match.end():], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end():end].strip()


def _first_nonempty_lines(text: str, *, max_lines: int = 4) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        lines.append(line)
        if len(lines) >= max_lines:
            break
    return lines


def _note_paths_from_digest(digest: str) -> list[str]:
    """Extract relative HumanAgentWiki note paths emitted in digest lines."""
    paths: list[str] = []
    pattern = re.compile(r"(?:→|->)\s+([^\n`]+?\.md)(?=$|\n)")
    for match in pattern.finditer(digest or ""):
        rel = match.group(1).strip().strip("`")
        if rel.startswith(("http://", "https://")):
            continue
        if rel not in paths:
            paths.append(rel)
    return paths


def _summarize_note_for_outcome(notes_dir: str | Path, rel_path: str) -> str:
    root = Path(notes_dir).expanduser().resolve()
    path = (root / rel_path).resolve()
    if root not in path.parents or not path.exists():
        return f"## {rel_path}\n**Status:** note not found for outcome.\n"
    text = path.read_text(encoding="utf-8")
    meta = _extract_frontmatter(text)
    title = meta.get("title") or path.stem.replace("-", " ").title()
    source = meta.get("channel") or meta.get("source_host") or meta.get("owner") or meta.get("from_addr") or meta.get("category") or "HumanAgentWiki"
    domain = meta.get("domain") or meta.get("topic") or meta.get("category") or ""
    summary = _extract_markdown_section(text, "Summary")
    key_points = _extract_markdown_section(text, "Key points") or _extract_markdown_section(text, "KEY TAKEAWAYS")
    action = _extract_markdown_section(text, "Actionable ideas") or _extract_markdown_section(text, "HOW TO APPLY THIS IN PRACTICE")
    if not key_points:
        key_points = summary
    if not action:
        action = _extract_markdown_section(text, "My take") or summary
    what_it_is = " ".join(_first_nonempty_lines(summary, max_lines=2))[:420]
    point_lines = _first_nonempty_lines(key_points, max_lines=4)
    action_lines = _first_nonempty_lines(action, max_lines=3)
    out = [
        f"## {title}",
        f"**Status:** in HumanAgentWiki",
        f"**Source:** {source}{(' · ' + domain) if domain else ''}",
        f"**Note:** `{rel_path}`",
        "",
    ]
    if what_it_is:
        out.extend(["**What it is:**", what_it_is, ""])
    if point_lines:
        out.append("**Key points:**")
        out.extend(line if line.startswith("-") else f"- {line}" for line in point_lines)
        out.append("")
    if action_lines:
        out.append("**What you should take from it:**")
        out.extend(line if line.startswith("-") else f"- {line}" for line in action_lines)
        out.append("")
    return "\n".join(out).strip()


def build_outcome_report(notes_dir: str | Path, digest: str) -> str:
    """Build a compact practical outcome report from note paths in a digest."""
    paths = [p for p in _note_paths_from_digest(digest) if not p.startswith("Daily Personal AI news/")]
    if not paths:
        return ""
    sections = [_summarize_note_for_outcome(notes_dir, rel) for rel in paths]
    return "## Outcome\n\n" + "\n\n".join(sections)


def write_daily_personal_ai_news_report(
    notes_dir: str | Path,
    digest: str,
    *,
    run_at: datetime | None = None,
    title: str = "AI Inbox Agent",
) -> str:
    """Persist the Telegram-ready AI news digest into HumanAgentWiki notes."""
    if not digest.strip():
        return ""
    timestamp = run_at or datetime.now().astimezone()
    day = timestamp.strftime("%Y-%m-%d")
    hour = timestamp.strftime("%H%M")
    rel_path = Path("Daily Personal AI news") / day / hour / "ai-inbox-agent.md"
    root = Path(notes_dir).expanduser().resolve()
    path = (root / rel_path).resolve()
    if root not in path.parents:
        raise ValueError(f"Refusing to write outside notes dir: {rel_path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = f"📬 {title}\n{digest.strip()}"
    content = f"""---
title: {title} - {day} {hour}
category: Daily Personal AI news
type: ai_news_digest
tags: [daily-ai-news, ai-inbox, telegram-digest]
source_type: ai_inbox_agent
dataset_use: rag
date: {day}
hour: {hour}
processed_at: {timestamp.isoformat()}
---

# {title} - {day} {hour}

## Telegram digest

```text
{rendered}
```

## Related
- [[Learning Gmail Inbox]]
- [[Daily Personal AI news]]
"""
    path.write_text(content, encoding="utf-8")
    return rel_path.as_posix()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process learning Gmail into HumanAgentWiki notes")
    parser.add_argument("--gmail-account", default=os.getenv("AI_INBOX_GMAIL_ACCOUNT", "learning"))
    parser.add_argument("--token-path", default=os.getenv("GOOGLE_TOKEN_PATH", DEFAULT_TOKEN_PATH))
    parser.add_argument("--query", default=os.getenv("AI_INBOX_GMAIL_QUERY", DEFAULT_QUERY))
    parser.add_argument("--max-emails", type=int, default=int(os.getenv("AI_INBOX_MAX_EMAILS", "5")))
    parser.add_argument("--notes-dir", default=os.getenv("NOTES_DIR", DEFAULT_NOTES_DIR))
    parser.add_argument("--humanagentwiki-dir", default=os.getenv("HUMANAGENTWIKI_DIR", DEFAULT_HAW_DIR))
    parser.add_argument("--state-db", default=os.getenv("AI_INBOX_STATE_DB", DEFAULT_STATE_DB))
    parser.add_argument(
        "--include-plain-emails",
        action="store_true",
        default=os.getenv("AI_INBOX_INCLUDE_PLAIN_EMAILS", "true").lower() in {"1", "true", "yes", "on"},
        help="Also summarize long unread emails with no links. Enabled by default for the dedicated learning Gmail account.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--with-outcome",
        action="store_true",
        help="After the digest, print a compact practical outcome summary from created HumanAgentWiki notes.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    client = GmailApiClient(args.token_path)
    messages = client.search_unread(args.query, max_results=args.max_emails)
    digest, successful_ids = process_messages(
        messages,
        notes_dir=args.notes_dir,
        state_db=args.state_db,
        gmail_account=args.gmail_account,
        dry_run=args.dry_run,
        include_plain_emails=args.include_plain_emails,
    )
    index_ok = True
    if successful_ids:
        index_ok, index_message = index_humanagentwiki(args.humanagentwiki_dir, args.notes_dir, dry_run=args.dry_run)
        if not index_ok:
            digest = (digest + "\n" if digest else "") + f"⚠️ {index_message}"
        if not args.dry_run and index_ok:
            client.mark_read(successful_ids)
    if digest:
        report_rel_path = ""
        if not args.dry_run and index_ok:
            report_rel_path = write_daily_personal_ai_news_report(args.notes_dir, digest)
            if report_rel_path:
                index_humanagentwiki(args.humanagentwiki_dir, args.notes_dir, dry_run=False)
        print("📬 AI Inbox Agent")
        print(digest)
        if report_rel_path:
            print(f"\n🗞️ Saved daily AI news digest → {report_rel_path}")
        if args.with_outcome:
            outcome = build_outcome_report(args.notes_dir, digest)
            if outcome:
                print()
                print(outcome)
        if args.dry_run:
            print("\nDRY RUN: no notes/state/email-read changes applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
