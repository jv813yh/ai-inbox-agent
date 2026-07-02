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
    "invest", "investovanie", "akcie", "akcia", "etf", "portfolio", "dividendy",
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
    return any(needle in haystack for needle in needles)


def classify_youtube_item(item: Mapping[str, Any], *, email_text: str = "") -> dict[str, Any]:
    """Return deterministic taxonomy metadata for a YouTube item."""
    raw_channel = str(item.get("channel") or "Unknown Channel").strip() or "Unknown Channel"
    normalized_channel = normalize_text(raw_channel)

    if normalized_channel in KNOWN_YOUTUBE_CHANNELS:
        result = dict(KNOWN_YOUTUBE_CHANNELS[normalized_channel])
    else:
        corpus = normalize_text(" ".join([
            raw_channel,
            str(item.get("title") or ""),
            str(item.get("summary") or ""),
            str(item.get("transcript_preview") or ""),
            email_text or "",
        ]))
        if _contains_any(corpus, INVESTMENT_KEYWORDS):
            result = {
                "domain": "Investovanie",
                "topic": "Investovanie",
                "channel_name": raw_channel,
                "method": "keyword_rule",
                "confidence": 0.75,
            }
        elif _contains_any(corpus, TECH_KEYWORDS):
            result = {
                "domain": "Technologie",
                "topic": "Technologie",
                "channel_name": raw_channel,
                "method": "keyword_rule",
                "confidence": 0.70,
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
