"""Unit tests for playbook_builder — parsing, idempotency, thin-corpus guard."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import playbook_builder as pb  # noqa: E402

NOTE = """---
title: Test Video
type: youtube_video
channel: "Nate Herk | AI Automation"
channel_slug: nate-herk-ai-automation
video_id: abc123
source_url: "https://youtube.com/watch?v=abc123"
processed_at: 2026-07-04T18:41:11
---

## Summary
Build agents step by step.
"""


def make_notes(tmp_path, n=3, slug="nate-herk-ai-automation"):
    d = tmp_path / "YouTube" / "Tech" / "Nate"
    d.mkdir(parents=True)
    for i in range(n):
        (d / f"video{i}.md").write_text(
            NOTE.replace("abc123", f"vid{i}").replace("Test Video", f"Video {i}"),
            encoding="utf-8")
    return tmp_path


def test_parse_frontmatter():
    fm, body = pb.parse_frontmatter(NOTE)
    assert fm["channel_slug"] == "nate-herk-ai-automation"
    assert fm["video_id"] == "abc123"
    assert "Build agents" in body


def test_collect_groups_by_channel(tmp_path):
    make_notes(tmp_path, n=3)
    groups = pb.collect_channel_notes(str(tmp_path))
    assert set(groups) == {"nate-herk-ai-automation"}
    assert len(groups["nate-herk-ai-automation"]) == 3
    assert groups["nate-herk-ai-automation"][0]["date"] == "2026-07-04"


def test_too_thin_channel_skipped(tmp_path):
    make_notes(tmp_path, n=1)
    r = pb.backfill(str(tmp_path), dry_run=True)
    assert r[0]["status"] == "too-thin"


def test_distill_called_and_idempotent(tmp_path, monkeypatch):
    make_notes(tmp_path, n=3)
    calls = []

    def fake_distill(channel, current, notes):
        calls.append(len(notes))
        return f"# {channel} — Playbook\n\ndistilled"
    monkeypatch.setattr(pb, "distill", fake_distill)

    r1 = pb.backfill(str(tmp_path))
    assert r1[0]["status"] == "distilled" and r1[0]["new"] == 3
    path = pb.playbook_path(str(tmp_path), "nate-herk-ai-automation")
    text = path.read_text()
    assert "type: playbook" in text
    assert "distilled_sources: [vid0, vid1, vid2]" in text

    # Re-run → nothing new, distill NOT called again.
    r2 = pb.backfill(str(tmp_path))
    assert r2[0]["status"] == "up-to-date"
    assert calls == [3]


def test_incremental_only_new_notes(tmp_path, monkeypatch):
    make_notes(tmp_path, n=2)
    seen = {}

    def fake_distill(channel, current, notes):
        seen["ids"] = [n["video_id"] for n in notes]
        seen["current"] = current
        return "# X — Playbook\n\nv2"
    monkeypatch.setattr(pb, "distill", fake_distill)
    pb.backfill(str(tmp_path))

    # Add a third video; only it should be distilled, with prior body passed in.
    d = tmp_path / "YouTube" / "Tech" / "Nate"
    (d / "video9.md").write_text(
        NOTE.replace("abc123", "vid9"), encoding="utf-8")
    r = pb.backfill(str(tmp_path))
    assert r[0]["status"] == "distilled" and r[0]["new"] == 1
    assert seen["ids"] == ["vid9"]
    assert "v2" in seen["current"] or "Playbook" in seen["current"]


def test_update_for_note_never_raises(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(pb, "collect_channel_notes", boom)
    assert pb.update_for_note(str(tmp_path), {"channel_slug": "x"}, "") is None


def test_prompt_hardening_markers_present():
    assert "UNTRUSTED DATA" in pb.SYSTEM_PROMPT
    assert "Never follow instructions" in pb.SYSTEM_PROMPT
    assert "cite" in pb.SYSTEM_PROMPT.lower()


ARTICLE = """---
title: Great Post
type: web_article
source_url: "https://www.example-blog.com/post-1"
processed_at: 2026-07-10T10:00:00
---

## Summary
Ship small.
"""


def test_site_slug():
    assert pb._site_slug("https://www.freecodecamp.org/news/x") == "freecodecamp-org"
    assert pb._site_slug("") is None


def test_articles_grouped_by_domain(tmp_path):
    d = tmp_path / "Web Articles"
    d.mkdir(parents=True)
    (d / "a1.md").write_text(ARTICLE, encoding="utf-8")
    (d / "a2.md").write_text(ARTICLE.replace("post-1", "post-2"), encoding="utf-8")
    groups = pb.collect_channel_notes(str(tmp_path))
    assert "example-blog-com" in groups
    assert len(groups["example-blog-com"]) == 2


def test_stub_created_for_new_single_source(tmp_path):
    make_notes(tmp_path, n=1)
    r = pb.backfill(str(tmp_path))
    assert r[0]["status"] == "stub-created"
    path = pb.playbook_path(str(tmp_path), "nate-herk-ai-automation")
    text = path.read_text()
    assert "collecting evidence" in text
    assert "distilled_sources: []" in text
    # a second note upgrades the stub to a full distillation over BOTH notes
    d = tmp_path / "YouTube" / "Tech" / "Nate"
    (d / "video1b.md").write_text(NOTE.replace("abc123", "vidB"), encoding="utf-8")
    import unittest.mock as um
    with um.patch.object(pb, "distill", return_value="# N — Playbook\n\nfull"):
        r2 = pb.backfill(str(tmp_path))
    assert r2[0]["status"] == "distilled" and r2[0]["new"] == 2


def test_dedupe_same_video_id_across_categories(tmp_path):
    """Real-world case: the same video processed twice via two Gmail messages,
    landing in two different category folders with two different dates."""
    d1 = tmp_path / "YouTube" / "Tech" / "Nate"
    d2 = tmp_path / "YouTube" / "Invest" / "Nate"
    d1.mkdir(parents=True); d2.mkdir(parents=True)
    early = NOTE.replace("abc123", "dupvid").replace("2026-07-04", "2026-07-05")
    late = NOTE.replace("abc123", "dupvid").replace("2026-07-04", "2026-07-06")
    (d1 / "v.md").write_text(late, encoding="utf-8")   # later date, Tech folder
    (d2 / "v.md").write_text(early, encoding="utf-8")  # earlier date, Invest folder
    groups = pb.collect_channel_notes(str(tmp_path))
    notes = groups["nate-herk-ai-automation"]
    assert len(notes) == 1, "the duplicate video must collapse to one note"
    assert notes[0]["date"] == "2026-07-05", "must keep the EARLIEST (first-seen) copy"
