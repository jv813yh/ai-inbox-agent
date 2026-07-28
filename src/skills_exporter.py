"""Export Channel Playbooks awareness to every agent on the server.

One SMALL skill/pointer per agent (deliberately not one per channel — that
would bloat every agent's context). The skill lists which playbooks exist and
teaches the agent how to use them: read the file for depth, or query the wiki
MCP (brain_search/brain_get) — both provider-independent.

Targets:
  Claude Code   ~/.claude/skills/channel-playbooks/SKILL.md
  Hermes        ~/.hermes/skills/channel-playbooks/SKILL.md
  Codex         ~/AGENTS.md                      (marker-delimited section)
  OpenClaw      ~/.openclaw/workspace/AGENTS.md  (marker-delimited section)

Marker sections are replaced idempotently; other file content is preserved
(and backed up once per run before the first write).

CLI:  python src/skills_exporter.py [--notes-dir DIR] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playbook_builder import parse_frontmatter  # noqa: E402

DEFAULT_NOTES_DIR = os.getenv("NOTES_DIR", "/home/jozef/humanagentwiki/notes")
HOME = Path.home()

BEGIN = "<!-- CHANNEL-PLAYBOOKS:BEGIN (auto-generated, do not edit inside) -->"
END = "<!-- CHANNEL-PLAYBOOKS:END -->"


def load_playbooks(notes_dir: str) -> list[dict]:
    out = []
    d = Path(notes_dir) / "Playbooks"
    for f in sorted(d.glob("*.md")) if d.exists() else []:
        fm, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
        if fm.get("type") != "playbook":
            continue
        out.append({
            "channel": fm.get("channel", f.stem),
            "slug": fm.get("channel_slug", f.stem),
            "sources": fm.get("sources_count", "?"),
            "updated": fm.get("updated", ""),
            "stub": "stub" in (fm.get("tags", "")),
            "path": str(f),
        })
    return out


def _index_lines(pbs: list[dict]) -> str:
    lines = []
    for p in pbs:
        flag = " (collecting — thin evidence)" if p["stub"] else ""
        lines.append(f"- **{p['channel']}** — {p['sources']} source(s), "
                     f"updated {p['updated'][:10]}{flag} → `{p['path']}`")
    return "\n".join(lines) or "- (none yet)"


def _core_text(pbs: list[dict], notes_dir: str) -> str:
    return f"""When the user asks "how would <creator> approach this?", wants advice in the
style of a channel/blog they follow, or asks to compare approaches across
sources, use the Channel Playbooks:

1. Read the creator's playbook file (paths below) — it is an evidence-cited
   distillation of their methodology. Trust its citations; if it says evidence
   is thin, say so to the user too.
2. For deeper/grounded answers, query the HumanAgentWiki MCP server
   (brain_search / brain_get) — playbooks and all source notes are indexed
   there. Filter by the creator's name or channel.
3. Cross-source briefs live in `{notes_dir}/Perspectives/`. A new one can be
   generated with:
   `cd /home/jozef/projects/ai-inbox-agent && .venv/bin/python src/playbook_builder.py --perspective "<topic>"`
4. Playbooks are derived from public content for personal use — they are
   interpretations, not the real person. Never present them as the creator's
   actual words unless quoting a cited source.

Available playbooks:

{_index_lines(pbs)}
"""


def render_skill_md(pbs: list[dict], notes_dir: str) -> str:
    desc = ("Evidence-cited methodology playbooks distilled from YouTube "
            "channels and blogs the user follows. Use when asked how a "
            "specific creator would approach a problem, for advice in their "
            "style, or to compare approaches across sources.")
    return (f"---\nname: channel-playbooks\ndescription: {desc}\n---\n\n"
            f"# Channel Playbooks\n\n{_core_text(pbs, notes_dir)}")


def _replace_section(path: Path, section: str, backup: bool = True) -> str:
    """Idempotently install a marker-delimited section into a markdown file."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if backup and path.exists() and BEGIN not in text:
        path.with_suffix(path.suffix + f".bak.{int(time.time())}").write_text(
            text, encoding="utf-8")
    block = f"{BEGIN}\n{section.strip()}\n{END}"
    if BEGIN in text and END in text:
        new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), block, text,
                     flags=re.S)
    else:
        new = (text.rstrip() + "\n\n" if text.strip() else "") + block + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    return "updated" if BEGIN in text else "created"


def export_all(notes_dir: str, dry_run: bool = False) -> list[dict]:
    pbs = load_playbooks(notes_dir)
    results = []
    skill_md = render_skill_md(pbs, notes_dir)
    agents_section = "## Channel Playbooks\n\n" + _core_text(pbs, notes_dir)

    targets = [
        ("claude", HOME / ".claude/skills/channel-playbooks/SKILL.md", "skill"),
        ("hermes", HOME / ".hermes/skills/channel-playbooks/SKILL.md", "skill"),
        ("codex", HOME / "AGENTS.md", "section"),
        ("openclaw", HOME / ".openclaw/workspace/AGENTS.md", "section"),
    ]
    for agent, path, kind in targets:
        if dry_run:
            results.append({"agent": agent, "path": str(path), "status": "would-write"})
            continue
        try:
            if kind == "skill":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(skill_md, encoding="utf-8")
                status = "written"
            else:
                status = _replace_section(path, agents_section)
            results.append({"agent": agent, "path": str(path), "status": status,
                            "playbooks": len(pbs)})
        except Exception as exc:  # noqa: BLE001 — one agent failing must not stop others
            results.append({"agent": agent, "path": str(path),
                            "status": f"error: {exc}"})
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="Export playbook skills to all agents")
    ap.add_argument("--notes-dir", default=DEFAULT_NOTES_DIR)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for r in export_all(args.notes_dir, args.dry_run):
        print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
