#!/usr/bin/env python3
"""
Prompt Builder — prepares data and applies the active prompt template.

All prompt strings live in prompts.py.
Switch a prompt by changing `latest_*` in prompts.py — nothing here changes.
"""

from typing import Dict

try:
    from .prompts import latest_article, latest_github, latest_plain_email, latest_youtube
except ImportError:
    from prompts import latest_article, latest_github, latest_plain_email, latest_youtube


class PromptBuilder:

    @staticmethod
    def youtube(title: str = "", description: str = "",
                transcript: str = "", email_context: str = "") -> str:
        """Apply the active YouTube prompt template."""
        context_parts = []
        if title:
            context_parts.append(f"Title: {title}")
        if description:
            context_parts.append(f"Description: {description[:2000]}")
        if transcript:
            context_parts.append(f"Transcript:\n{transcript[:12000]}")
        if email_context:
            context_parts.append(f"Email content (use this as primary context if no transcript):\n{email_context[:3000]}")

        context = "\n\n".join(context_parts)
        return latest_youtube.format(title=title, context=context)

    @staticmethod
    def github(repo_info: Dict) -> str:
        """Apply the active GitHub prompt template."""
        return latest_github.format(
            repo=repo_info["repo"],
            owner=repo_info["owner"],
            url=repo_info["url"],
            description=repo_info.get("description", "No description"),
            stars=repo_info.get("stars", 0),
            forks=repo_info.get("forks", 0),
            language=repo_info.get("language", "Unknown"),
            topics=", ".join(repo_info.get("topics", [])),
            updated_at=repo_info.get("updated_at", "Unknown"),
            readme=repo_info.get("readme", "Not available")[:3000],
        )

    @staticmethod
    def plain_email(subject: str, from_addr: str, body: str) -> str:
        """Apply the active plain-email prompt template."""
        return latest_plain_email.format(
            subject=subject,
            from_addr=from_addr,
            body=body[:3000],
        )

    @staticmethod
    def article(title: str, url: str, content: str) -> str:
        """Apply the active web-article prompt template."""
        return latest_article.format(
            title=title,
            url=url,
            content=content[:4000],
        )
