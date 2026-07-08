import json
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
            channel_text = (notes_dir / "YouTube Channels" / "agent-lab.md").read_text(encoding="utf-8")
            self.assertIn("video_count: 1", channel_text)
            self.assertIn("[Building Safe AI Agents](../YouTube/Technologie/Agent Lab/", channel_text)
            self.assertIn("Source: https://www.youtube.com/watch?v=abc123xyz00", channel_text)
            self.assertIn("transcript: `true`", channel_text)
            self.assertIn("Safe agents need boundaries.", channel_text)

    def test_youtube_channel_index_shows_structured_video_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            writer = AgentWikiWriter(notes_dir)
            item = {
                "url": "https://www.youtube.com/watch?v=sum123xyz00",
                "video_id": "sum123xyz00",
                "title": "AI Code Review Patterns",
                "channel": "Agent Lab",
                "summary": """🎬 INTRO
This video explains how to review AI-generated code safely.

📝 WHAT IS THIS VIDEO ABOUT?
It is about treating AI code as untrusted input and routing it through tests, lint, security scans, code review, and runtime verification.

🔑 KEY TAKEAWAYS
- AI-generated code needs the same review path as external pull requests.
- Runtime checks catch bugs that static review misses.

💼 ACTIONABLE IDEAS
- Add a mandatory trust pipeline before merging AI code.
- Keep verification evidence next to the change summary.
""",
                "has_full_transcript": True,
                "processed_at": "2026-07-06T12:00:00+00:00",
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
            email_meta = {"from": "sender@example.com", "subject": "review", "date": "today", "message_id": "msg-channel-summary"}

            rel_path = writer.write_youtube_note(item, email_meta=email_meta, gmail_account="learning")
            writer.upsert_youtube_index(item, rel_path)
            channel_text = (notes_dir / "YouTube Channels" / "agent-lab.md").read_text(encoding="utf-8")

            self.assertIn("  - **Summary:** It is about treating AI code as untrusted input", channel_text)
            self.assertIn("  - **Key points:**", channel_text)
            self.assertIn("    - AI-generated code needs the same review path", channel_text)
            self.assertIn("  - **Actionable ideas:**", channel_text)
            self.assertIn("    - Add a mandatory trust pipeline", channel_text)

    def test_writes_youtube_note_populates_structured_sections_from_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            writer = AgentWikiWriter(notes_dir)
            item = {
                "url": "https://www.youtube.com/watch?v=ship1234567",
                "video_id": "ship1234567",
                "title": "Multi-Agent Architecture That Ships",
                "channel": "Factory",
                "summary": """🎬 INTRO
A useful production multi-agent architecture talk.

🔑 KEY TAKEAWAYS
- Validation contracts are essential for reliable agents.
- Serial execution can beat naive parallelism when context matters.

🚀 HOW TO APPLY THIS IN PRACTICE
- Define orchestrator, worker, and validator roles before coding.
- Add concrete validation contracts for each agent task.

🧩 ENTITIES
- Factory: company building software engineering agents.
- Luke Alvoeiro: presenter of the architecture.

📣 CLAIMS
- Validation contracts reduce drift in long-running agent workflows.
- Per-role model selection improves cost and quality.

💼 ACTIONABLE IDEAS
- Build a small validator library for agent workflows.
- Track model quality per agent role.

🧠 MY TAKE:
Validation infrastructure is the practical wedge.
""",
                "has_full_transcript": False,
                "processed_at": "2026-07-04T12:00:00+00:00",
                "classification": {
                    "domain": "Technologie",
                    "topic": "AI Agents",
                    "channel_name": "Factory",
                    "channel_slug": "factory",
                    "dataset_use": "rag",
                    "source_type": "youtube",
                    "method": "keyword_rule",
                    "confidence": 0.8,
                },
            }
            email_meta = {"from": "sender@example.com", "subject": "agents", "date": "today", "message_id": "msg-structured"}

            rel_path = writer.write_youtube_note(item, email_meta=email_meta, gmail_account="learning")
            text = (notes_dir / rel_path).read_text(encoding="utf-8")

            self.assertIn("## Key points\n- Validation contracts are essential", text)
            self.assertIn("## Entities\n- Factory: company building software engineering agents.", text)
            self.assertIn("## Claims\n- Validation contracts reduce drift", text)
            self.assertIn("## Actionable ideas\n- Build a small validator library", text)
            self.assertNotIn("## Key points\n\n## Entities", text)
            self.assertNotIn("## Entities\n\n## Claims", text)
            self.assertNotIn("## Claims\n\n## Actionable ideas", text)

    def test_writes_ai_learning_note_from_learning_worthy_youtube_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            writer = AgentWikiWriter(notes_dir)
            item = {
                "url": "https://www.youtube.com/watch?v=learn123456",
                "video_id": "learn123456",
                "title": "How to Design Agent Skills",
                "channel": "Agent Lab",
                "summary": """🔑 KEY TAKEAWAYS
- A good agent skill has trigger conditions, exact steps, pitfalls, and verification.
- Save reusable workflows as procedural memory instead of relying on chat history.

🚀 HOW TO APPLY THIS IN PRACTICE
- Write a SKILL.md with frontmatter, step-by-step workflow, and verification checklist.
- Link the skill back to the source video and note why it was extracted.
""",
                "model": "claude-opus-4-6",
                "processed_at": "2026-07-05T12:00:00+00:00",
                "classification": {
                    "domain": "Technologie",
                    "topic": "AI Agents",
                    "channel_name": "Agent Lab",
                    "channel_slug": "agent-lab",
                    "dataset_use": "rag",
                    "source_type": "youtube",
                    "method": "keyword_rule",
                    "confidence": 0.8,
                },
            }
            source_rel = "YouTube/Technologie/Agent Lab/2026-07-05--learn123456--how-to-design-agent-skills.md"

            learning_rel = writer.write_learning_note_if_useful(
                item,
                source_rel_path=source_rel,
                source_type="youtube_video",
                gmail_account="learning",
            )

            self.assertIsNotNone(learning_rel)
            self.assertTrue(learning_rel.startswith("AI Learning System/Technologie/"))
            text = (notes_dir / learning_rel).read_text(encoding="utf-8")
            self.assertIn("category: AI Learning System", text)
            self.assertIn("type: ai_learning_note", text)
            self.assertIn("source_note: \"YouTube/Technologie/Agent Lab/2026-07-05--learn123456--how-to-design-agent-skills.md\"", text)
            self.assertIn("source_type: youtube_video", text)
            self.assertIn("processed_by_model: claude-opus-4-6", text)
            self.assertIn("extraction_reason:", text)
            self.assertIn("## Learning artifact", text)
            self.assertIn("A good agent skill has trigger conditions", text)
            self.assertIn("## Source linkage", text)
            self.assertIn("[[How to Design Agent Skills]]", text)
            self.assertIn("[[AI Learning System Index]]", text)

    def test_skips_ai_learning_note_when_summary_has_no_reusable_learning_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = AgentWikiWriter(Path(tmp))
            item = {
                "url": "https://example.com/news",
                "title": "Short Market News",
                "summary": "A short news update without reusable process or learning detail.",
                "processed_at": "2026-07-05T12:00:00+00:00",
                "classification": {"domain": "Ostatne", "topic": "News"},
            }

            learning_rel = writer.write_learning_note_if_useful(
                item,
                source_rel_path="Web Articles/Ostatne/example.com/news.md",
                source_type="web_article",
                gmail_account="learning",
            )

            self.assertIsNone(learning_rel)

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


    def test_writes_article_note_and_idempotent_index_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            writer = AgentWikiWriter(notes_dir)
            item = {
                "url": "https://example.com/blog/useful",
                "title": "Useful Article",
                "summary": "Article summary.",
                "my_take": "Use this in backend automation.",
                "processed_at": "2026-07-04T10:00:00+00:00",
            }
            email_meta = {"from": "sender@example.com", "subject": "Article", "date": "today", "message_id": "msg-art"}

            rel_path = writer.write_article_note(item, email_meta=email_meta, gmail_account="learning")
            text = (notes_dir / rel_path).read_text(encoding="utf-8")

            self.assertTrue(rel_path.startswith("Web Articles/Technologie/example.com/"))
            self.assertIn("category: Web Articles", text)
            self.assertIn("type: web_article", text)
            self.assertIn("domain: Technologie", text)
            self.assertIn("source_host: example.com", text)
            self.assertIn("dataset_use: rag", text)
            self.assertIn("## Where Jozef could use it", text)

            writer.upsert_article_index(item, rel_path)
            writer.upsert_article_index(item, rel_path)
            index_text = (notes_dir / "Indexes" / "web-article-index.md").read_text(encoding="utf-8")
            self.assertEqual(index_text.count("- [[Useful Article]]"), 1)

    def test_writes_plain_email_note_under_month_folder_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            writer = AgentWikiWriter(notes_dir)
            item = {
                "subject": "Long useful email",
                "from_addr": "sender@example.com",
                "summary": "Email summary.",
                "my_take": "Follow up later.",
                "processed_at": "2026-07-04T10:00:00+00:00",
            }
            email_meta = {"from": "sender@example.com", "subject": "Long useful email", "date": "today", "message_id": "msg-email"}

            rel_path = writer.write_plain_email_note(item, email_meta=email_meta, gmail_account="learning")
            text = (notes_dir / rel_path).read_text(encoding="utf-8")

            self.assertTrue(rel_path.startswith("Emails/Ostatne/2026-07/"))
            self.assertIn("category: Emails", text)
            self.assertIn("type: plain_email", text)
            self.assertIn("from_addr: \"sender@example.com\"", text)
            self.assertIn("## Summary", text)

            writer.upsert_plain_email_index(item, rel_path)
            writer.upsert_plain_email_index(item, rel_path)
            index_text = (notes_dir / "Indexes" / "plain-email-index.md").read_text(encoding="utf-8")
            self.assertEqual(index_text.count("- [[Long useful email]]"), 1)

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
            self.assertIn("## Practical value for Jozef", text)
            self.assertIn("Evaluate whether this solves or demonstrates: Email AI agent", text)
            self.assertIn("Reusable patterns to inspect: agents, gmail", text)
            self.assertIn("Follow-up for Jozef: extract one concrete backend/cloud/agent workflow idea", text)
            self.assertNotIn("Review for AI agents / backend / automation ideas", text)
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
    def test_writes_rag_bundle_for_youtube_source_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            writer = AgentWikiWriter(notes_dir)
            item = {
                "url": "https://www.youtube.com/watch?v=rag123xyz00",
                "video_id": "rag123xyz00",
                "title": "AI Boom and Chip Rotation",
                "channel": "Dominik Kovarik",
                "summary": """🔑 KEY TAKEAWAYS
- Market breadth matters more than headline index levels.
- AI capex must eventually prove return on investment.

📣 CLAIMS
- Chip weakness can signal sector rotation rather than immediate AI boom failure.
- Investors should track whether AI infrastructure spending turns into cash flow.

💼 ACTIONABLE IDEAS
- Compare semiconductor ETFs against equal-weight S&P 500.
- Track earnings commentary about AI capex ROI.
""",
                "transcript": "Market breadth matters. AI capex must prove ROI. Watch chip weakness and sector rotation.",
                "transcript_preview": "Market breadth matters. AI capex must prove ROI.",
                "has_full_transcript": True,
                "processed_at": "2026-07-08T07:00:00+00:00",
                "classification": {
                    "domain": "Investovanie",
                    "topic": "AI capex",
                    "channel_name": "Dominik Kovarik",
                    "channel_slug": "dominik-kovarik",
                    "dataset_use": "rag",
                    "source_type": "youtube",
                    "method": "known_channel_map",
                    "confidence": 0.95,
                },
            }
            email_meta = {"from": "sender@example.com", "subject": "rag", "date": "today", "message_id": "msg-rag"}
            source_rel = writer.write_youtube_note(item, email_meta=email_meta, gmail_account="learning")

            bundle = writer.write_rag_bundle(item, source_rel_path=source_rel, source_type="youtube_video", gmail_account="learning")

            self.assertIn("raw_source", bundle)
            self.assertIn("extracted_knowledge", bundle)
            self.assertIn("concept_notes", bundle)
            self.assertIn("rag_chunks", bundle)
            raw_text = (notes_dir / bundle["raw_source"]).read_text(encoding="utf-8")
            self.assertIn("type: raw_transcript", raw_text)
            self.assertIn("sha256:", raw_text)
            self.assertIn("Market breadth matters", raw_text)
            extracted = json.loads((notes_dir / bundle["extracted_knowledge"]).read_text(encoding="utf-8"))
            self.assertEqual(extracted["source_note"], source_rel)
            self.assertEqual(extracted["domain"], "Investovanie")
            self.assertIn("claims", extracted)
            self.assertIn("actionable_checklists", extracted)
            self.assertGreaterEqual(len(extracted["claims"]), 2)
            self.assertTrue(any(path.startswith("Concepts/Investovanie/") for path in bundle["concept_notes"]))
            concept_text = (notes_dir / bundle["concept_notes"][0]).read_text(encoding="utf-8")
            self.assertIn("type: concept_candidate", concept_text)
            self.assertIn("source_notes:", concept_text)
            chunks = [json.loads(line) for line in (notes_dir / bundle["rag_chunks"]).read_text(encoding="utf-8").splitlines()]
            self.assertGreaterEqual(len(chunks), 3)
            self.assertTrue(all("metadata" in chunk and "text" in chunk for chunk in chunks))
            self.assertTrue(any(chunk["metadata"].get("chunk_type") == "raw_transcript" for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
