import tempfile
import unittest
from pathlib import Path

from src.agentwiki_writer import AgentWikiWriter, slugify


class AgentWikiWriterTests(unittest.TestCase):
    def test_slugify_removes_path_separators_and_keeps_readable_text(self):
        self.assertEqual(slugify("../../My Cool Video: AI Agents!?"), "my-cool-video-ai-agents")
        self.assertEqual(slugify(""), "untitled")

    def test_writes_youtube_note_and_idempotent_index_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            writer = AgentWikiWriter(notes_dir)
            item = {
                "url": "https://www.youtube.com/watch?v=abc123xyz00",
                "video_id": "abc123xyz00",
                "title": "Building Safe AI Agents",
                "channel": "Agent Lab",
                "summary": "📌 ONE-LINE SUMMARY: Safe agents need boundaries.",
                "my_take": "🧠 MY TAKE: Useful for Hermes orchestration.",
                "has_full_transcript": True,
                "transcript_preview": "hello transcript",
                "processed_at": "2026-07-01T12:00:00+00:00",
                "classification": {
                    "domain": "Technologie",
                    "topic": "AI Agents",
                    "channel_name": "Agent Lab",
                    "channel_slug": "agent-lab",
                    "dataset_use": "rag",
                    "source_type": "youtube",
                    "method": "known_channel_map",
                    "confidence": 0.95,
                },
            }
            email_meta = {
                "from": "sender@example.com",
                "subject": "YouTube: agents",
                "date": "Wed, 1 Jul 2026 12:00:00 +0000",
                "message_id": "gmail-msg-1",
            }

            rel_path = writer.write_youtube_note(item, email_meta=email_meta, gmail_account="learning")
            note_path = notes_dir / rel_path

            self.assertTrue(note_path.exists())
            self.assertTrue(rel_path.startswith("YouTube/Technologie/Agent Lab/"))
            text = note_path.read_text(encoding="utf-8")
            self.assertIn("category: YouTube", text)
            self.assertIn("domain: Technologie", text)
            self.assertIn("topic: AI Agents", text)
            self.assertIn("channel_slug: agent-lab", text)
            self.assertIn("dataset_use: rag", text)
            self.assertIn("source_type: youtube", text)
            self.assertIn("type: youtube_video", text)
            self.assertIn("source_url: \"https://www.youtube.com/watch?v=abc123xyz00\"", text)
            self.assertIn("## Summary", text)
            self.assertIn("## My take", text)
            self.assertIn("[[YouTube Technologie Index]]", text)

            writer.upsert_youtube_index(item, rel_path)
            writer.upsert_youtube_index(item, rel_path)
            index_text = (notes_dir / "Indexes" / "youtube-technologie-index.md").read_text(encoding="utf-8")
            self.assertEqual(index_text.count("Building Safe AI Agents"), 1)

    def test_writes_investment_youtube_note_under_channel_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            writer = AgentWikiWriter(notes_dir)
            item = {
                "url": "https://www.youtube.com/watch?v=inv123xyz00",
                "video_id": "inv123xyz00",
                "title": "ETF portfolio pre zaciatocnikov",
                "channel": "Kapitalista",
                "summary": "Investicne zhrnutie.",
                "my_take": "Pouzitelne pre osobne poznamky.",
                "has_full_transcript": True,
                "transcript_preview": "ETF a dlhodobe investovanie",
                "processed_at": "2026-07-01T12:00:00+00:00",
                "classification": {
                    "domain": "Investovanie",
                    "topic": "ETF",
                    "channel_name": "Kapitalista",
                    "channel_slug": "kapitalista",
                    "dataset_use": "rag",
                    "source_type": "youtube",
                    "method": "known_channel_map",
                    "confidence": 0.95,
                },
            }
            email_meta = {"from": "sender@example.com", "subject": "YouTube investovanie", "date": "today", "message_id": "msg-invest"}

            rel_path = writer.write_youtube_note(item, email_meta=email_meta, gmail_account="learning")
            self.assertTrue(rel_path.startswith("YouTube/Investovanie/Kapitalista/"))
            text = (notes_dir / rel_path).read_text(encoding="utf-8")
            self.assertIn("domain: Investovanie", text)
            self.assertIn("topic: ETF", text)

            writer.upsert_youtube_index(item, rel_path)
            index_text = (notes_dir / "Indexes" / "youtube-investovanie-index.md").read_text(encoding="utf-8")
            self.assertIn("ETF portfolio pre zaciatocnikov", index_text)

    def test_writes_github_note_and_idempotent_index_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            writer = AgentWikiWriter(notes_dir)
            item = {
                "url": "https://github.com/jv813yh/ai-inbox-agent",
                "owner": "jv813yh",
                "repo": "ai-inbox-agent",
                "description": "Email AI agent",
                "stars": 7,
                "forks": 1,
                "language": "Python",
                "topics": ["agents", "gmail"],
                "summary": "Analyzes inbox links.",
                "my_take": "Useful for automation.",
                "readme_preview": "# ai-inbox-agent",
                "processed_at": "2026-07-01T12:00:00+00:00",
            }
            email_meta = {"from": "sender@example.com", "subject": "GitHub project", "date": "today", "message_id": "msg-2"}

            rel_path = writer.write_github_note(item, email_meta=email_meta, gmail_account="learning")
            note_path = notes_dir / rel_path

            self.assertTrue(note_path.exists())
            text = note_path.read_text(encoding="utf-8")
            self.assertIn("category: GitHub Projects", text)
            self.assertIn("type: github_project", text)
            self.assertIn("owner: jv813yh", text)
            self.assertIn("## What it is", text)
            self.assertIn("[[GitHub Project Index]]", text)

            writer.upsert_github_index(item, rel_path)
            writer.upsert_github_index(item, rel_path)
            index_text = (notes_dir / "Indexes" / "github-project-index.md").read_text(encoding="utf-8")
            self.assertEqual(index_text.count("- [[jv813yh/ai-inbox-agent]]"), 1)

    def test_frontmatter_scalar_sanitizes_newlines(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            writer = AgentWikiWriter(notes_dir)
            item = {
                "url": "https://github.com/bad/repo",
                "owner": "bad\ninjected: yes",
                "repo": "repo",
                "stars": 0,
                "forks": 0,
                "language": "Python",
                "summary": "summary",
                "my_take": "take",
                "readme_preview": "preview",
                "processed_at": "2026-07-01T12:00:00+00:00",
            }
            email_meta = {"from": "sender@example.com", "subject": "GitHub project", "date": "today", "message_id": "msg-2"}

            rel_path = writer.write_github_note(item, email_meta=email_meta, gmail_account="learning")
            text = (notes_dir / rel_path).read_text(encoding="utf-8")
            frontmatter = text.split("---", 2)[1]

            self.assertNotIn("\ninjected: yes", frontmatter)
            self.assertIn("owner: \"bad injected: yes\"", frontmatter)


if __name__ == "__main__":
    unittest.main()
