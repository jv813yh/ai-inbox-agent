#!/usr/bin/env python3
"""Deterministic content taxonomy for ai-inbox-agent notes.

This module intentionally uses simple, auditable rules first. It prepares
folder placement and metadata for later RAG/fine-tuning dataset work without
letting an LLM arbitrarily move files around.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping


KNOWN_YOUTUBE_CHANNELS: dict[str, dict[str, Any]] = {
    "ai engineer": {
        "domain": "Technologie",
        "topic": "AI Agents",
        "channel_name": "AI Engineer",
        "method": "known_channel_map",
        "confidence": 0.95,
    },
    "anthropic": {
        "domain": "Technologie",
        "topic": "AI Agents",
        "channel_name": "Anthropic",
        "method": "known_channel_map",
        "confidence": 0.95,
    },
    "austin marchese": {
        "domain": "Technologie",
        "topic": "AI Agents",
        "channel_name": "Austin Marchese",
        "method": "known_channel_map",
        "confidence": 0.90,
    },
    "sequoia capital": {
        "domain": "Technologie",
        "topic": "AI Agents",
        "channel_name": "Sequoia Capital",
        "method": "known_channel_map",
        "confidence": 0.90,
    },
    "computerphile": {
        "domain": "Technologie",
        "topic": "Computer Science",
        "channel_name": "Computerphile",
        "method": "known_channel_map",
        "confidence": 0.92,
    },
    "jean lee": {
        "domain": "Technologie",
        "topic": "Software Engineering",
        "channel_name": "Jean Lee",
        "method": "known_channel_map",
        "confidence": 0.90,
    },
    "chase ai": {
        "domain": "Technologie",
        "topic": "AI Agents",
        "channel_name": "Chase AI",
        "method": "known_channel_map",
        "confidence": 0.92,
    },
    "nate herk | ai automation": {
        "domain": "Technologie",
        "topic": "AI Automation",
        "channel_name": "Nate Herk | AI Automation",
        "method": "known_channel_map",
        "confidence": 0.92,
    },
    "google cloud tech": {
        "domain": "Technologie",
        "topic": "Cloud AI",
        "channel_name": "Google Cloud Tech",
        "method": "known_channel_map",
        "confidence": 0.92,
    },
    "greg isenberg": {
        "domain": "Technologie",
        "topic": "AI Business",
        "channel_name": "Greg Isenberg",
        "method": "known_channel_map",
        "confidence": 0.90,
    },
    "kapitalista": {
        "domain": "Investovanie",
        "topic": "Investovanie",
        "channel_name": "Kapitalista",
        "method": "known_channel_map",
        "confidence": 0.95,
    },
    "dominik kovarik": {
        "domain": "Investovanie",
        "topic": "Investovanie",
        "channel_name": "Dominik Kovarik",
        "method": "known_channel_map",
        "confidence": 0.95,
    },
}

INVESTMENT_KEYWORDS = {
    "investovanie", "investing", "investor", "investori", "investič", "investic",
    "akcie", "akcia", "etf", "portfolio", "dividendy", "trading", "trader",
    "trhy", "burza", "dlhopisy", "crypto", "krypto", "bitcoin", "financ", "kapital",
}

TECH_KEYWORDS = {
    "python", "backend", "api", "azure", "cloud", "devops", "llm", "agent", "agents",
    "ai", "machine learning", "github", "docker", "kubernetes", "server", "database",
    "programming", "software", "automation", "openai", "claude",
}


def normalize_text(value: str) -> str:
    """Lowercase and strip diacritics for matching."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    asciiish = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", asciiish.lower()).strip()


def channel_slug(value: str) -> str:
    normalized = normalize_text(value)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug or "unknown-channel"


def _contains_any(haystack: str, needles: set[str]) -> bool:
    """Keyword match with word boundaries for short tokens.

    Avoid false positives such as keyword "ai" matching inside "email" while
    still allowing stem-like terms such as "invest" or "financ" to match.
    """
    for needle in needles:
        escaped = re.escape(needle)
        if " " in needle or len(needle) <= 3:
            if re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", haystack):
                return True
        elif needle in haystack:
            return True
    return False


def classify_youtube_item(item: Mapping[str, Any], *, email_text: str = "") -> dict[str, Any]:
    """Return deterministic taxonomy metadata for a YouTube item."""
    raw_channel = str(item.get("channel") or "Unknown Channel").strip() or "Unknown Channel"
    normalized_channel = normalize_text(raw_channel)

    if normalized_channel in KNOWN_YOUTUBE_CHANNELS:
        result = dict(KNOWN_YOUTUBE_CHANNELS[normalized_channel])
    else:
        item_corpus = normalize_text(" ".join([
            raw_channel,
            str(item.get("title") or ""),
            str(item.get("summary") or ""),
            str(item.get("transcript_preview") or ""),
        ]))
        email_corpus = normalize_text(email_text or "")

        # Classify primarily from the specific video/channel. A single forwarded
        # email can contain a mixed list (finance + AI + coding); using the whole
        # email first misroutes unrelated videos under the wrong domain.
        if _contains_any(item_corpus, INVESTMENT_KEYWORDS):
            result = {
                "domain": "Investovanie",
                "topic": "Investovanie",
                "channel_name": raw_channel,
                "method": "keyword_rule",
                "confidence": 0.75,
            }
        elif _contains_any(item_corpus, TECH_KEYWORDS):
            result = {
                "domain": "Technologie",
                "topic": "Technologie",
                "channel_name": raw_channel,
                "method": "keyword_rule",
                "confidence": 0.70,
            }
        elif _contains_any(email_corpus, INVESTMENT_KEYWORDS):
            result = {
                "domain": "Investovanie",
                "topic": "Investovanie",
                "channel_name": raw_channel,
                "method": "email_keyword_fallback",
                "confidence": 0.55,
            }
        elif _contains_any(email_corpus, TECH_KEYWORDS):
            result = {
                "domain": "Technologie",
                "topic": "Technologie",
                "channel_name": raw_channel,
                "method": "email_keyword_fallback",
                "confidence": 0.55,
            }
        else:
            result = {
                "domain": "Ostatne",
                "topic": "Ostatne",
                "channel_name": raw_channel,
                "method": "fallback",
                "confidence": 0.30,
            }

    result.setdefault("channel_name", raw_channel)
    result["channel_slug"] = channel_slug(str(result["channel_name"]))
    result.setdefault("dataset_use", "rag")
    result.setdefault("source_type", "youtube")
    return result


def folder_parts_for_youtube(classification: Mapping[str, Any]) -> list[str]:
    """Return HumanAgentWiki relative folder parts for a classified YouTube item."""
    domain = str(classification.get("domain") or "Ostatne").strip() or "Ostatne"
    channel_name = str(classification.get("channel_name") or "Unknown Channel").strip() or "Unknown Channel"
    # Keep human-readable folder names; AgentWikiWriter still validates paths.
    safe_domain = domain.replace("/", " ").replace("\\", " ")
    safe_channel = channel_name.replace("/", " ").replace("\\", " ")
    return ["YouTube", " ".join(safe_domain.split()), " ".join(safe_channel.split())]


PRODUCTIVITY_KEYWORDS = {
    "productivity", "workflow", "notion", "calendar", "task", "todo", "habit", "focus",
    "learning", "course", "tutorial", "study", "education", "self-educated", "book", "books",
    "writing", "research", "knowledge", "notes", "obsidian", "rag", "fine tuning", "fine-tuning",
}

BUSINESS_KEYWORDS = {
    "startup", "business", "marketing", "sales", "product", "saas", "customer", "founder",
    "revenue", "pricing", "growth", "company", "market",
}

DOMAIN_FALLBACK_BY_HOST = {
    "github.com": "Technologie",
    "anthropic.com": "Technologie",
    "openai.com": "Technologie",
    "microsoft.com": "Technologie",
    "techcommunity.microsoft.com": "Technologie",
    "devblogs.microsoft.com": "Technologie",
    "learn.microsoft.com": "Technologie",
    "kdnuggets.com": "Technologie",
    "arxiv.org": "Technologie",
    "medium.com": "Ostatne",
    "substack.com": "Ostatne",
}


def _domain_topic_from_corpus(corpus: str, *, host: str = "") -> tuple[str, str, str, float]:
    """Return (domain, topic, method, confidence) from deterministic rules."""
    normalized_host = normalize_text(host)
    for known_host, domain in DOMAIN_FALLBACK_BY_HOST.items():
        if known_host in normalized_host:
            return domain, domain, "known_host_map", 0.80
    if _contains_any(corpus, INVESTMENT_KEYWORDS):
        return "Investovanie", "Investovanie", "keyword_rule", 0.75
    if _contains_any(corpus, TECH_KEYWORDS):
        return "Technologie", "Technologie", "keyword_rule", 0.72
    if _contains_any(corpus, PRODUCTIVITY_KEYWORDS):
        return "Produktivita", "Produktivita", "keyword_rule", 0.65
    if _contains_any(corpus, BUSINESS_KEYWORDS):
        return "Biznis", "Biznis", "keyword_rule", 0.65
    return "Ostatne", "Ostatne", "fallback", 0.30


def classify_article_item(item: Mapping[str, Any], *, email_text: str = "") -> dict[str, Any]:
    """Return taxonomy metadata for a generic web article."""
    from urllib.parse import urlparse

    url = str(item.get("url") or "")
    host = urlparse(url).netloc.lower().removeprefix("www.")
    corpus = normalize_text(" ".join([
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
        str(item.get("my_take") or ""),
        email_text or "",
        host,
    ]))
    domain, topic, method, confidence = _domain_topic_from_corpus(corpus, host=host)
    return {
        "domain": domain,
        "topic": topic,
        "source_host": host or "unknown-domain",
        "method": method,
        "confidence": confidence,
        "dataset_use": "rag",
        "source_type": "web_article",
    }


def classify_plain_email_item(item: Mapping[str, Any], *, email_text: str = "") -> dict[str, Any]:
    """Return taxonomy metadata for an email without supported links."""
    from_addr = str(item.get("from_addr") or "")
    corpus = normalize_text(" ".join([
        str(item.get("subject") or ""),
        str(item.get("summary") or ""),
        str(item.get("my_take") or ""),
        email_text or "",
        from_addr,
    ]))
    domain, topic, method, confidence = _domain_topic_from_corpus(corpus, host=from_addr)
    return {
        "domain": domain,
        "topic": topic,
        "method": method,
        "confidence": confidence,
        "dataset_use": "rag",
        "source_type": "plain_email",
    }


def folder_parts_for_article(classification: Mapping[str, Any]) -> list[str]:
    domain = str(classification.get("domain") or "Ostatne").replace("/", " ").replace("\\", " ")
    host = str(classification.get("source_host") or "unknown-domain").replace("/", " ").replace("\\", " ")
    return ["Web Articles", " ".join(domain.split()), " ".join(host.split())]


def folder_parts_for_plain_email(classification: Mapping[str, Any], month: str) -> list[str]:
    domain = str(classification.get("domain") or "Ostatne").replace("/", " ").replace("\\", " ")
    return ["Emails", " ".join(domain.split()), month]
