#!/usr/bin/env python3
"""Write ai-inbox-agent outputs as HumanAgentWiki/Obsidian Markdown notes."""

from __future__ import annotations

import hashlib
import json
import re
import posixpath
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

try:
    from .content_classifier import classify_article_item, classify_plain_email_item, classify_youtube_item, folder_parts_for_article, folder_parts_for_plain_email, folder_parts_for_youtube
except ImportError:
    from content_classifier import classify_article_item, classify_plain_email_item, classify_youtube_item, folder_parts_for_article, folder_parts_for_plain_email, folder_parts_for_youtube


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


_YOUTUBE_SUMMARY_HEADERS = {
    "INTRO",
    "WHAT IS THIS VIDEO ABOUT",
    "MAIN LEARNING OBJECTIVES",
    "DETAILED NOTES",
    "KEY TAKEAWAYS",
    "HOW TO APPLY THIS IN PRACTICE",
    "ACTIONABLE IDEAS",
    "MY TAKE",
    "ANALOGIES AND EXAMPLES",
    "CLAIMS",
    "CONNECTIONS TO OTHER CONCEPTS",
    "ENTITIES",
    "QUESTIONS TO REFLECT ON",
    "RELEVANCE FOR MODERN DEVELOPERS",
    "FURTHER READING",
}


def _normalize_summary_header(line: str) -> str:
    text = re.sub(r"^[^A-Za-z0-9]+", "", line.strip())
    text = text.rstrip(":").strip()
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", text).upper()
    return " ".join(text.split())


def _extract_summary_section(summary: str, *headers: str) -> str:
    targets = {_normalize_summary_header(header) for header in headers}
    lines = summary.splitlines()
    collecting = False
    collected: list[str] = []
    for line in lines:
        normalized = _normalize_summary_header(line)
        is_known_header = normalized in _YOUTUBE_SUMMARY_HEADERS
        if normalized in targets:
            collecting = True
            continue
        if collecting and is_known_header:
            break
        if collecting:
            collected.append(line.rstrip())
    return "\n".join(collected).strip()


def _first_non_empty_lines(text: str, *, limit: int = 3) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    selected = lines[:limit]
    if all(line.startswith(("- ", "1.", "2.", "3.")) for line in selected):
        return "\n".join(selected)
    return "\n".join(f"- {line.lstrip('- ').strip()}" for line in selected)


def _youtube_structured_sections(item: Mapping[str, Any], classification: Mapping[str, Any]) -> Mapping[str, str]:
    summary = str(item.get("summary") or "")
    title = str(item.get("title") or "YouTube video")
    channel = str(classification.get("channel_name") or item.get("channel") or "Unknown Channel")
    domain = str(classification.get("domain") or "Ostatne")
    topic = str(classification.get("topic") or domain)

    my_take = str(item.get("my_take") or "").strip() or _extract_summary_section(summary, "MY TAKE")
    key_points = (
        _extract_summary_section(summary, "KEY TAKEAWAYS")
        or _extract_summary_section(summary, "MAIN LEARNING OBJECTIVES")
        or _first_non_empty_lines(summary, limit=3)
        or "- See the Summary section above for the main learning points."
    )
    actionable = (
        _extract_summary_section(summary, "ACTIONABLE IDEAS")
        or _extract_summary_section(summary, "HOW TO APPLY THIS IN PRACTICE")
        or _extract_summary_section(summary, "FURTHER READING")
        or "- Turn the strongest idea from the summary into a small experiment or checklist.\n- Save follow-up links or tools mentioned in the video as separate AgentWiki notes."
    )

    # Keep these sections lightweight and deterministic. They make notes useful for
    # RAG even when the LLM summary did not return explicit entity/claim fields.
    explicit_entities = _extract_summary_section(summary, "ENTITIES")
    entities = explicit_entities or "\n".join(
        f"- {value}"
        for value in [title, channel, domain, topic]
        if value and value != "Unknown"
    )
    claims_source = _extract_summary_section(summary, "CLAIMS") or key_points or summary
    claims = _first_non_empty_lines(claims_source, limit=3) or "- No explicit claims extracted; rely on the Summary section."

    return {
        "my_take": my_take or "- No separate take extracted; see Summary for the main interpretation.",
        "key_points": key_points,
        "entities": entities,
        "claims": claims,
        "actionable_ideas": actionable,
    }


_LEARNING_KEYWORDS = {
    "skill", "skills", "checklist", "workflow", "playbook", "runbook", "step-by-step",
    "fine tuning", "fine-tuning", "finetuning", "dataset", "evaluation", "benchmark",
    "agent", "agents", "automation", "orchestration", "architecture", "pattern", "framework",
    "debugging", "testing", "deploy", "production", "prompt", "rag", "mcp",
}


def _learning_signal(summary: str) -> tuple[bool, str]:
    """Detect whether a summary contains reusable learning/process content."""
    lower = summary.lower()
    matched = sorted({kw for kw in _LEARNING_KEYWORDS if kw in lower})
    has_action_section = bool(
        _extract_summary_section(summary, "HOW TO APPLY THIS IN PRACTICE")
        or _extract_summary_section(summary, "ACTIONABLE IDEAS")
        or _extract_summary_section(summary, "MAIN LEARNING OBJECTIVES")
    )
    has_enough_signal = len(matched) >= 2 or (has_action_section and matched)
    if not has_enough_signal:
        return False, ""
    reason_bits = []
    if matched:
        reason_bits.append("matched learning keywords: " + ", ".join(matched[:8]))
    if has_action_section:
        reason_bits.append("contains actionable learning/application sections")
    return True, "; ".join(reason_bits)


def _learning_artifact(summary: str) -> str:
    """Return compact reusable learning content from an existing summary."""
    parts: list[str] = []
    for label, headers in [
        ("Key ideas", ("KEY TAKEAWAYS", "MAIN LEARNING OBJECTIVES")),
        ("Procedure / application", ("HOW TO APPLY THIS IN PRACTICE", "ACTIONABLE IDEAS")),
        ("Detailed notes", ("DETAILED NOTES",)),
    ]:
        section = ""
        for header in headers:
            section = _extract_summary_section(summary, header)
            if section:
                break
        if section:
            parts.append(f"### {label}\n{section.strip()}")
    if not parts:
        parts.append(_first_non_empty_lines(summary, limit=6))
    return "\n\n".join(part for part in parts if part).strip()


def _bullet_items(text: str, *, limit: int = 8) -> list[str]:
    items: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(('- ', '* ')):
            item = line[2:].strip()
        elif re.match(r"^\d+[.)]\s+", line):
            item = re.sub(r"^\d+[.)]\s+", "", line).strip()
        else:
            continue
        if item and item not in items:
            items.append(item)
        if len(items) >= limit:
            break
    return items


def _chunk_text(text: str, *, max_chars: int = 1200) -> list[str]:
    clean = "\n".join(line.strip() for line in (text or "").splitlines() if line.strip())
    if not clean:
        return []
    paragraphs = re.split(r"\n{2,}", clean)
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if not para:
            continue
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current.strip())
            current = para
        else:
            current = f"{current}\n\n{para}".strip() if current else para
    if current:
        chunks.append(current.strip())
    return chunks or [clean[:max_chars]]


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
    def _read_frontmatter(path: Path) -> tuple[dict[str, str], str]:
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n"):
            return {}, raw
        end = raw.find("\n---", 4)
        if end == -1:
            return {}, raw
        fm: dict[str, str] = {}
        for line in raw[4:end].splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            text = value.strip()
            if len(text) >= 2 and text[0] == text[-1] == '"':
                text = text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            fm[key.strip()] = text
        return fm, raw[end + 4 :].lstrip()

    @staticmethod
    def _extract_markdown_section(body: str, heading: str) -> str:
        pattern = re.compile(
            rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)",
            re.IGNORECASE | re.MULTILINE,
        )
        match = pattern.search(body)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _compact_preview(text: str, *, max_length: int = 220) -> str:
        lines = [line.strip().lstrip("- ").strip() for line in text.splitlines() if line.strip()]
        lines = [line for line in lines if not re.fullmatch(r"[^A-Za-z0-9]*[A-Z0-9][A-Z0-9 ./'-]*:?", line)]
        preview = " ".join(lines[:2]).strip()
        if len(preview) > max_length:
            return preview[: max_length - 1].rstrip() + "..."
        return preview

    @staticmethod
    def _first_bullet_lines(text: str, *, limit: int = 2) -> list[str]:
        bullets: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("- "):
                bullets.append(stripped)
            elif bullets:
                break
            if len(bullets) >= limit:
                break
        return bullets

    @classmethod
    def _channel_video_detail_lines(cls, body: str) -> list[str]:
        """Return compact, structured lines for a video inside its channel hub."""
        summary = cls._extract_markdown_section(body, "Summary")
        about = (
            _extract_summary_section(summary, "WHAT IS THIS VIDEO ABOUT")
            or cls._compact_preview(summary, max_length=260)
        )
        key_points = cls._extract_markdown_section(body, "Key points") or _extract_summary_section(summary, "KEY TAKEAWAYS")
        actionable = cls._extract_markdown_section(body, "Actionable ideas") or _extract_summary_section(
            summary, "ACTIONABLE IDEAS", "HOW TO APPLY THIS IN PRACTICE"
        )

        lines: list[str] = []
        about_preview = cls._compact_preview(about, max_length=280)
        if about_preview:
            lines.append(f"  - **Summary:** {about_preview}")
        key_bullets = cls._first_bullet_lines(key_points, limit=2)
        if key_bullets:
            lines.append("  - **Key points:**")
            lines.extend(f"    {bullet}" for bullet in key_bullets)
        action_bullets = cls._first_bullet_lines(actionable, limit=2)
        if action_bullets:
            lines.append("  - **Actionable ideas:**")
            lines.extend(f"    {bullet}" for bullet in action_bullets)
        return lines

    @staticmethod
    def _email_source(email_meta: Mapping[str, Any]) -> str:
        def clean(value: Any) -> str:
            return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())

        return (
            f"From: {clean(email_meta.get('from', 'Unknown'))}\n"
            f"Subject: {clean(email_meta.get('subject', ''))}\n"
            f"Date: {clean(email_meta.get('date', ''))}\n"
            f"Message-ID: {clean(email_meta.get('message_id', ''))}"
        )

    @staticmethod
    def _youtube_classification(item: Mapping[str, Any]) -> Mapping[str, Any]:
        existing = item.get("classification")
        if isinstance(existing, Mapping):
            return existing
        return classify_youtube_item(item)

    @staticmethod
    def _rag_classification(item: Mapping[str, Any], source_type: str) -> Mapping[str, Any]:
        existing = item.get("classification")
        if isinstance(existing, Mapping):
            return existing
        if source_type == "youtube_video":
            return classify_youtube_item(item)
        if source_type == "web_article":
            return classify_article_item(item)
        if source_type == "plain_email":
            return classify_plain_email_item(item)
        return {}

    @staticmethod
    def _rag_source_id(item: Mapping[str, Any], source_type: str) -> str:
        if source_type == "youtube_video":
            return str(item.get("video_id") or AgentWikiWriter._video_id_from_url(str(item.get("url", ""))) or slugify(str(item.get("title") or "youtube")))
        if source_type == "github_project":
            return f"{item.get('owner', 'unknown')}/{item.get('repo', 'unknown')}"
        return str(item.get("url") or item.get("subject") or item.get("title") or source_type)

    def _append_jsonl(self, rel_path: str, rows: list[dict[str, Any]]) -> str:
        path = self._safe_path(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing_ids: set[str] = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    existing_ids.add(str(json.loads(line).get("id")))
                except Exception:
                    continue
        with path.open("a", encoding="utf-8") as fh:
            for row in rows:
                if row["id"] in existing_ids:
                    continue
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                existing_ids.add(row["id"])
        return path.relative_to(self.notes_dir).as_posix()

    def write_rag_bundle(
        self,
        item: Mapping[str, Any],
        *,
        source_rel_path: str,
        source_type: str,
        gmail_account: str,
    ) -> dict[str, Any]:
        """Write RAG-ready artifacts for one processed source.

        This creates four layers:
        1. Raw Sources: immutable-ish transcript/source text with sha256.
        2. Extracted Knowledge: structured JSON claims/principles/actions.
        3. Concepts: candidate concept pages that can later be curated/merged.
        4. RAG/Chunks: JSONL chunks with metadata for vector/keyword indexing.
        """
        classification = self._rag_classification(item, source_type)
        domain = str(classification.get("domain") or item.get("domain") or "Ostatne")
        topic = str(classification.get("topic") or item.get("topic") or domain)
        title = str(item.get("title") or item.get("subject") or item.get("url") or "RAG source")
        source_id = self._rag_source_id(item, source_type)
        source_slug = slugify(source_id, max_length=40)
        title_slug = slugify(title, max_length=70)
        processed_at = str(item.get("processed_at") or "")
        date_prefix = processed_at[:10] or "undated"
        summary = str(item.get("summary") or "")
        raw_text = str(item.get("transcript") or item.get("full_transcript") or item.get("transcript_preview") or item.get("body") or summary)
        raw_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

        source_folder = {
            "youtube_video": "YouTube",
            "web_article": "Articles",
            "plain_email": "Emails",
            "github_project": "GitHub",
        }.get(source_type, slugify(source_type))
        channel_or_host = str(classification.get("channel_name") or item.get("channel") or classification.get("source_host") or self._domain_from_url(str(item.get("url", ""))) or "source")
        raw_rel = f"Raw Sources/{source_folder}/{slugify(channel_or_host)}/{date_prefix}--{source_slug}--{title_slug}.md"
        raw_front = _frontmatter({
            "title": title,
            "type": "raw_transcript" if source_type == "youtube_video" else "raw_source",
            "source_type": source_type,
            "source_id": source_id,
            "source_url": item.get("url", ""),
            "source_note": source_rel_path,
            "domain": domain,
            "topic": topic,
            "language": item.get("language", ""),
            "transcript_quality": item.get("transcript_quality", "unknown"),
            "sha256": raw_hash,
            "dataset_use": "rag",
            "gmail_account": gmail_account,
            "processed_at": processed_at,
        })
        raw_front = raw_front.replace(f"source_note: {source_rel_path}", f"source_note: \"{source_rel_path}\"")
        self._write_note(raw_rel, raw_front + f"\n\n# Raw source - {title}\n\n{raw_text}")

        sections = _youtube_structured_sections(item, classification) if source_type == "youtube_video" else {
            "key_points": _extract_summary_section(summary, "KEY TAKEAWAYS") or _first_non_empty_lines(summary, limit=5),
            "claims": _extract_summary_section(summary, "CLAIMS") or _first_non_empty_lines(summary, limit=5),
            "actionable_ideas": _extract_summary_section(summary, "ACTIONABLE IDEAS", "HOW TO APPLY THIS IN PRACTICE") or str(item.get("my_take") or ""),
            "entities": str(item.get("title") or ""),
            "my_take": str(item.get("my_take") or ""),
        }
        claims = _bullet_items(sections.get("claims", ""), limit=12) or _bullet_items(sections.get("key_points", ""), limit=8)
        principles = _bullet_items(sections.get("key_points", ""), limit=12)
        actions = _bullet_items(sections.get("actionable_ideas", ""), limit=12)
        concepts = []
        for value in [topic, *principles[:4], *claims[:4]]:
            clean = re.sub(r"^[A-Za-z ]+:\s*", "", value).strip(" .")
            if clean and len(clean) >= 4:
                concepts.append(clean[:90])
        seen_concepts: list[str] = []
        for concept in concepts:
            if slugify(concept) not in [slugify(c) for c in seen_concepts]:
                seen_concepts.append(concept)
        extracted = {
            "schema_version": 1,
            "source_note": source_rel_path,
            "raw_source": raw_rel,
            "source_type": source_type,
            "source_id": source_id,
            "source_url": item.get("url", ""),
            "title": title,
            "domain": domain,
            "topic": topic,
            "speaker_or_channel": channel_or_host,
            "claim_kind_default": "author_opinion" if domain == "Investovanie" else "source_claim",
            "claims": [{"text": claim, "claim_kind": "author_opinion" if domain == "Investovanie" else "source_claim", "confidence": "medium"} for claim in claims],
            "principles": principles,
            "frameworks": seen_concepts[:8],
            "examples": _bullet_items(sections.get("entities", ""), limit=8),
            "metrics": [c for c in claims + principles if re.search(r"\d|%|roi|capex|dma|etf", c, re.I)],
            "risks": [c for c in claims + principles if re.search(r"risk|weak|slab|warning|pozor|volatil|drawdown|bubble|hype", c, re.I)],
            "actionable_checklists": actions,
            "open_questions": _bullet_items(_extract_summary_section(summary, "QUESTIONS TO REFLECT ON"), limit=8),
            "processed_at": processed_at,
        }
        extracted_rel = f"Extracted Knowledge/{source_folder}/{date_prefix}--{source_slug}--{title_slug}.json"
        extracted_path = self._safe_path(extracted_rel)
        extracted_path.parent.mkdir(parents=True, exist_ok=True)
        extracted_path.write_text(json.dumps(extracted, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        concept_notes: list[str] = []
        for concept in seen_concepts[:6]:
            concept_slug = slugify(concept, max_length=70)
            concept_rel = f"Concepts/{domain}/{concept_slug}.md"
            path = self._safe_path(concept_rel)
            if path.exists():
                text = path.read_text(encoding="utf-8")
                link = f"- `{source_rel_path}`"
                if link not in text:
                    text = text.rstrip() + f"\n{link}\n"
                    path.write_text(text, encoding="utf-8")
            else:
                front = _frontmatter({
                    "title": concept,
                    "type": "concept_candidate",
                    "domain": domain,
                    "topic": topic,
                    "tags": ["concept", "rag", "ai-inbox", domain],
                    "source_notes": [source_rel_path],
                    "source_type": source_type,
                    "confidence": "medium",
                    "dataset_use": "rag",
                    "updated": date_prefix,
                })
                body = f"""# {concept}

## Definition / working meaning
Candidate concept extracted from `{source_rel_path}`.

## Source-backed insights
- Review and merge this candidate into a durable concept note when it appears across multiple sources.

## Source notes
- `{source_rel_path}`

## Related
- [[{title}]]
- [[RAG Index]]
"""
                self._write_note(concept_rel, front + "\n\n" + body)
            concept_notes.append(concept_rel)

        chunk_rows: list[dict[str, Any]] = []
        base_meta = {
            "source_type": source_type,
            "source_id": source_id,
            "source_url": item.get("url", ""),
            "source_note": source_rel_path,
            "raw_source": raw_rel,
            "extracted_knowledge": extracted_rel,
            "domain": domain,
            "topic": topic,
            "title": title,
            "channel": channel_or_host,
            "dataset_use": "rag",
        }
        for idx, chunk in enumerate(_chunk_text(raw_text), start=1):
            chunk_rows.append({"id": f"{source_type}:{source_id}:raw:{idx:04d}", "text": chunk, "metadata": {**base_meta, "chunk_type": "raw_transcript" if source_type == "youtube_video" else "raw_source", "chunk_index": idx}})
        for name, text in [("summary", summary), ("claims", "\n".join(claims)), ("actions", "\n".join(actions)), ("concepts", "\n".join(seen_concepts))]:
            if text.strip():
                chunk_rows.append({"id": f"{source_type}:{source_id}:{name}", "text": text.strip(), "metadata": {**base_meta, "chunk_type": name, "chunk_index": 0}})
        chunks_rel = f"RAG/Chunks/{date_prefix}--{source_slug}--{title_slug}.jsonl"
        self._append_jsonl(chunks_rel, chunk_rows)
        self._upsert_index("Indexes/rag-index.md", "RAG Index", ["index", "rag", "ai-inbox"], f"- [[{title}]] — {domain} / {topic} — source `{source_rel_path}` — chunks `{chunks_rel}`")
        return {"raw_source": raw_rel, "extracted_knowledge": extracted_rel, "concept_notes": concept_notes, "rag_chunks": chunks_rel}

    def write_learning_note_if_useful(
        self,
        item: Mapping[str, Any],
        *,
        source_rel_path: str,
        source_type: str,
        gmail_account: str,
    ) -> str | None:
        """Write a reusable AI Learning System note when source content has learning signal.

        This is deterministic and uses the already-generated source summary; it does
        not make another LLM call. The note is linked back to the original source note
        so RAG can trace where the learning came from.
        """
        summary = str(item.get("summary") or "")
        should_write, reason = _learning_signal(summary)
        if not should_write:
            return None

        classification = item.get("classification") if isinstance(item.get("classification"), Mapping) else {}
        domain = str(classification.get("domain") or item.get("domain") or "Ostatne")
        topic = str(classification.get("topic") or item.get("topic") or domain)
        title = str(item.get("title") or item.get("subject") or item.get("url") or "Learning note")
        date_prefix = str(item.get("processed_at", ""))[:10] or "undated"
        source_id = str(item.get("video_id") or item.get("url") or title)
        rel_path = f"AI Learning System/{domain}/{date_prefix}--{slugify(source_id, max_length=32)}--{slugify(title)}.md"
        artifact = _learning_artifact(summary)
        processed_by_model = str(item.get("model") or item.get("processed_by_model") or "ai-inbox-agent summarizer")

        front = _frontmatter(
            {
                "title": title,
                "category": "AI Learning System",
                "type": "ai_learning_note",
                "tags": ["ai-learning", "learning-system", "ai-inbox", domain],
                "domain": domain,
                "topic": topic,
                "source_note": source_rel_path,
                "source_url": item.get("url", ""),
                "source_type": source_type,
                "source_title": title,
                "processed_by_model": processed_by_model,
                "extracted_by": "ai-inbox-agent learning extractor",
                "extraction_reason": reason,
                "dataset_use": "rag",
                "gmail_account": gmail_account,
                "processed_at": item.get("processed_at", ""),
            }
        )
        # Quote source_note for readability/path safety in frontmatter snapshots.
        front = front.replace(f"source_note: {source_rel_path}", f"source_note: \"{source_rel_path}\"")
        body = f"""# {title}

## Learning artifact
{artifact}

## Why this was extracted
{reason}

## Source linkage
- Source note: `{source_rel_path}`
- Source type: {source_type}
- Source URL: {item.get('url', '')}
- Processed by model: {processed_by_model}

## Related
- [[{title}]]
- [[AI Learning System Index]]
"""
        return self._write_note(rel_path, front + "\n\n" + body)

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
        classification = self._youtube_classification(item)
        folder = "/".join(folder_parts_for_youtube(classification))
        rel_path = f"{folder}/{date_prefix}--{slugify(video_id)}--{slugify(title)}.md"
        domain = str(classification.get("domain") or "Ostatne")
        topic = str(classification.get("topic") or domain)
        channel_name = str(classification.get("channel_name") or item.get("channel") or "Unknown Channel")
        sections = _youtube_structured_sections(item, classification)

        front = _frontmatter(
            {
                "title": title,
                "category": "YouTube",
                "domain": domain,
                "topic": topic,
                "type": "youtube_video",
                "tags": ["youtube", "video", "ai-inbox", "learning-gmail", domain],
                "source_url": item.get("url", ""),
                "source_type": classification.get("source_type", "youtube"),
                "video_id": video_id,
                "channel": channel_name,
                "channel_slug": classification.get("channel_slug", "unknown-channel"),
                "dataset_use": classification.get("dataset_use", "rag"),
                "classification_method": classification.get("method", "fallback"),
                "classification_confidence": classification.get("confidence", 0),
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
{sections['my_take']}

## Key points
{sections['key_points']}

## Entities
{sections['entities']}

## Claims
{sections['claims']}

## Actionable ideas
{sections['actionable_ideas']}

## Key metadata
- Domain: {domain}
- Topic: {topic}
- Channel: {channel_name}
- Transcript available: {'yes' if item.get('has_full_transcript') else 'no'}

## Source metadata
- Source type: youtube
- Dataset use: {classification.get('dataset_use', 'rag')}
- Classification method: {classification.get('method', 'fallback')}
- Classification confidence: {classification.get('confidence', 0)}

## Transcript preview
{item.get('transcript_preview', '').strip()}

## Related
- [[YouTube {domain} Index]]
- [[Learning Gmail Inbox]]
"""
        return self._write_note(rel_path, front + "\n\n" + body)

    @staticmethod
    def _github_practical_value(item: Mapping[str, Any]) -> str:
        """Create a useful non-generic practical value section for GitHub notes."""
        description = str(item.get("description") or "").strip()
        language = str(item.get("language") or "").strip()
        topics = [str(t).strip() for t in (item.get("topics") or []) if str(t).strip()]
        readme = str(item.get("readme_preview") or "").strip()
        bullets: list[str] = []
        if description:
            bullets.append(f"- Evaluate whether this solves or demonstrates: {description}")
        if topics:
            bullets.append(f"- Reusable patterns to inspect: {', '.join(topics[:8])}.")
        if language and language != "Unknown":
            bullets.append(f"- Code angle: inspect the {language} implementation for APIs, architecture, examples, tests, and integration boundaries.")
        if readme:
            first_line = next((line.strip().lstrip('# ').strip() for line in readme.splitlines() if line.strip()), "")
            if first_line:
                bullets.append(f"- README signal to verify: {first_line[:220]}")
        bullets.append("- Follow-up for Jozef: extract one concrete backend/cloud/agent workflow idea, not just bookmark the repo.")
        return "\n".join(bullets)

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
        practical_value = self._github_practical_value(item)
        body = f"""# {name}

Source: {item.get('url', '')}

Email source:
{self._email_source(email_meta)}

## What it is
{item.get('summary', '').strip()}

## My take
{item.get('my_take', '').strip()}

## Practical value for Jozef
{practical_value}

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

    @staticmethod
    def _domain_from_url(url: str) -> str:
        host = urlparse(url or "").netloc.lower().removeprefix("www.")
        return host or "unknown-domain"

    def write_article_note(
        self,
        item: Mapping[str, Any],
        *,
        email_meta: Mapping[str, Any],
        gmail_account: str,
    ) -> str:
        title = str(item.get("title") or item.get("url") or "Web Article")
        url = str(item.get("url") or "")
        domain = self._domain_from_url(url)
        classification = dict(item.get("classification") or classify_article_item(item))
        classification.setdefault("source_host", domain)
        date_prefix = str(item.get("processed_at", ""))[:10] or "undated"
        folder = "/".join(folder_parts_for_article(classification))
        rel_path = f"{folder}/{date_prefix}--{slugify(title)}.md"

        front = _frontmatter(
            {
                "title": title,
                "category": "Web Articles",
                "type": "web_article",
                "tags": ["article", "web", "ai-inbox", "learning-gmail"],
                "source_url": url,
                "source_type": "web_article",
                "domain": classification.get("domain", domain),
                "topic": classification.get("topic", classification.get("domain", domain)),
                "source_host": classification.get("source_host", domain),
                "classification_method": classification.get("method", "fallback"),
                "classification_confidence": classification.get("confidence", 0.30),
                "dataset_use": "rag",
                "gmail_account": gmail_account,
                "gmail_message_id": email_meta.get("message_id", ""),
                "processed_at": item.get("processed_at", ""),
            }
        )
        body = f"""# {title}

Source: {url}

Email source:
{self._email_source(email_meta)}

## Summary
{item.get('summary', '').strip()}

## My take
{item.get('my_take', '').strip()}

## Where Jozef could use it
- Review for AI agents, backend, automation, investing, learning, or product ideas depending on the article topic.

## How to use it
- Open the source link for full context.
- Convert useful claims into follow-up tasks or notes.
- Use the metadata and summary later for RAG retrieval.

## Source metadata
- Source type: web_article
- Domain: {classification.get('domain', domain)}
- Topic: {classification.get('topic', classification.get('domain', domain))}
- Source host: {classification.get('source_host', domain)}
- Dataset use: rag

## Related
- [[Web Article Index]]
- [[Learning Gmail Inbox]]
"""
        return self._write_note(rel_path, front + "\n\n" + body)

    def write_plain_email_note(
        self,
        item: Mapping[str, Any],
        *,
        email_meta: Mapping[str, Any],
        gmail_account: str,
    ) -> str:
        subject = str(item.get("subject") or email_meta.get("subject") or "Email")
        from_addr = str(item.get("from_addr") or email_meta.get("from") or "")
        date_prefix = str(item.get("processed_at", ""))[:10] or "undated"
        month = date_prefix[:7] if len(date_prefix) >= 7 else "undated"
        classification = dict(item.get("classification") or classify_plain_email_item(item))
        folder = "/".join(folder_parts_for_plain_email(classification, month))
        rel_path = f"{folder}/{date_prefix}--{slugify(subject)}.md"

        front = _frontmatter(
            {
                "title": subject,
                "category": "Emails",
                "type": "plain_email",
                "tags": ["email", "ai-inbox", "learning-gmail"],
                "from_addr": from_addr,
                "subject": subject,
                "domain": classification.get("domain", "Ostatne"),
                "topic": classification.get("topic", classification.get("domain", "Ostatne")),
                "classification_method": classification.get("method", "fallback"),
                "classification_confidence": classification.get("confidence", 0.30),
                "dataset_use": "rag",
                "gmail_account": gmail_account,
                "gmail_message_id": email_meta.get("message_id", ""),
                "processed_at": item.get("processed_at", ""),
            }
        )
        body = f"""# {subject}

Email source:
{self._email_source(email_meta)}

## Summary
{item.get('summary', '').strip()}

## My take
{item.get('my_take', '').strip()}

## Action items

## Source metadata
- Source type: plain_email
- Domain: {classification.get('domain', 'Ostatne')}
- Topic: {classification.get('topic', classification.get('domain', 'Ostatne'))}
- Dataset use: rag

## Related
- [[Plain Email Index]]
- [[Learning Gmail Inbox]]
"""
        return self._write_note(rel_path, front + "\n\n" + body)

    def upsert_youtube_index(self, item: Mapping[str, Any], rel_note_path: str) -> str:
        title = str(item.get("title") or item.get("url") or "YouTube Video")
        classification = self._youtube_classification(item)
        domain = str(classification.get("domain") or "Ostatne")
        topic = str(classification.get("topic") or domain)
        channel_name = str(classification.get("channel_name") or item.get("channel") or "Unknown Channel")
        entry = f"- [[{title}]] — {channel_name} — {topic} — {item.get('url', '')} — `{rel_note_path}`"
        domain_index = self._upsert_index(
            f"Indexes/youtube-{slugify(domain)}-index.md",
            f"YouTube {domain} Index",
            ["index", "youtube", "ai-inbox", domain],
            entry,
        )
        self._upsert_index("Indexes/youtube-video-index.md", "YouTube Video Index", ["index", "youtube", "ai-inbox"], entry)
        self.upsert_youtube_channel_index(item, rel_note_path)
        return domain_index

    def upsert_youtube_channel_index(self, item: Mapping[str, Any], rel_note_path: str) -> str:
        classification = self._youtube_classification(item)
        channel_name = str(classification.get("channel_name") or item.get("channel") or "Unknown Channel")
        channel_slug = str(classification.get("channel_slug") or slugify(channel_name, fallback="unknown-channel"))
        videos: list[dict[str, Any]] = []
        youtube_root = self.notes_dir / "YouTube"
        if youtube_root.exists():
            for path in sorted(youtube_root.rglob("*.md")):
                fm, body = self._read_frontmatter(path)
                if (fm.get("channel_slug") or "") != channel_slug and (fm.get("channel") or "") != channel_name:
                    continue
                rel = path.relative_to(self.notes_dir).as_posix()
                detail_lines = self._channel_video_detail_lines(body)
                videos.append(
                    {
                        "title": fm.get("title") or path.stem,
                        "rel_path": rel,
                        "href": posixpath.relpath(rel, start="YouTube Channels"),
                        "source_url": fm.get("source_url") or "",
                        "domain": fm.get("domain") or fm.get("topic") or "Ostatne",
                        "topic": fm.get("topic") or "",
                        "video_id": fm.get("video_id") or "",
                        "transcript": fm.get("transcript_available") or "false",
                        "detail_lines": detail_lines,
                    }
                )

        if not any(v["rel_path"] == rel_note_path for v in videos):
            title = str(item.get("title") or item.get("url") or "YouTube Video")
            videos.append(
                {
                    "title": title,
                    "rel_path": rel_note_path,
                    "href": posixpath.relpath(rel_note_path, start="YouTube Channels"),
                    "source_url": str(item.get("url") or ""),
                    "domain": str(classification.get("domain") or "Ostatne"),
                    "topic": str(classification.get("topic") or ""),
                    "video_id": str(item.get("video_id") or ""),
                    "transcript": "true" if item.get("has_full_transcript") else "false",
                    "detail_lines": self._channel_video_detail_lines(f"## Summary\n{str(item.get('summary') or '').strip()}"),
                }
            )

        videos.sort(key=lambda v: (v["domain"], v["title"].lower(), v["rel_path"]))
        domains = sorted({v["domain"] for v in videos if v["domain"]})
        front = _frontmatter(
            {
                "title": f"YouTube Channel - {channel_name}",
                "category": "YouTube Channels",
                "type": "hub",
                "channel": channel_name,
                "channel_slug": channel_slug,
                "video_count": len(videos),
                "domains": domains,
                "source_type": "youtube_channel_index",
                "dataset_use": "rag",
            }
        )
        video_lines: list[str] = []
        for video in videos:
            source = f" — Source: {video['source_url']}" if video["source_url"] else ""
            topic = f" / {video['topic']}" if video["topic"] and video["topic"] != video["domain"] else ""
            video_lines.append(
                f"- [{video['title']}]({video['href']}){source} — `{video['domain']}{topic}` — transcript: `{video['transcript']}`"
            )
            for detail_line in video.get("detail_lines") or []:
                video_lines.append(str(detail_line))

        body = f"""# YouTube Channel - {channel_name}

Channel slug: `{channel_slug}`
Video count: **{len(videos)}**

## Videos
{chr(10).join(video_lines) if video_lines else "- No videos indexed yet."}

## Filter/search helpers
- channel: `{channel_name}`
- channel_slug: `{channel_slug}`
- source_type: `youtube_channel_index`
"""
        return self._write_note(f"YouTube Channels/{channel_slug}.md", front + "\n\n" + body)

    def upsert_github_index(self, item: Mapping[str, Any], rel_note_path: str) -> str:
        name = f"{item.get('owner', 'unknown')}/{item.get('repo', 'unknown')}"
        entry = f"- [[{name}]] — {item.get('language', 'Unknown')} / ⭐{item.get('stars', 0)} — {item.get('url', '')} — `{rel_note_path}`"
        return self._upsert_index("Indexes/github-project-index.md", "GitHub Project Index", ["index", "github", "ai-inbox"], entry)

    def upsert_article_index(self, item: Mapping[str, Any], rel_note_path: str) -> str:
        title = str(item.get("title") or item.get("url") or "Web Article")
        entry = f"- [[{title}]] — {self._domain_from_url(str(item.get('url', '')))} — {item.get('url', '')} — `{rel_note_path}`"
        return self._upsert_index("Indexes/web-article-index.md", "Web Article Index", ["index", "article", "web", "ai-inbox"], entry)

    def upsert_plain_email_index(self, item: Mapping[str, Any], rel_note_path: str) -> str:
        subject = str(item.get("subject") or "Email")
        entry = f"- [[{subject}]] — {item.get('from_addr', 'Unknown')} — `{rel_note_path}`"
        return self._upsert_index("Indexes/plain-email-index.md", "Plain Email Index", ["index", "email", "ai-inbox"], entry)

    def upsert_learning_index(self, item: Mapping[str, Any], rel_note_path: str, source_rel_path: str) -> str:
        title = str(item.get("title") or item.get("subject") or item.get("url") or "Learning note")
        classification = item.get("classification") if isinstance(item.get("classification"), Mapping) else {}
        domain = str(classification.get("domain") or item.get("domain") or "Ostatne")
        topic = str(classification.get("topic") or item.get("topic") or domain)
        entry = f"- [[{title}]] — {domain} / {topic} — source `{source_rel_path}` — `{rel_note_path}`"
        return self._upsert_index("Indexes/ai-learning-system-index.md", "AI Learning System Index", ["index", "ai-learning", "ai-inbox"], entry)

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
