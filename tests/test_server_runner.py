import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

from src.gmail_api_client import GmailMessage
from src.server_runner import (
    DEFAULT_QUERY,
    classify_links,
    process_messages,
    source_id_for_article_url,
    source_id_for_github_url,
    source_id_for_youtube_url,
    write_daily_personal_ai_news_report,
)
from src.state_store import StateStore


class ServerRunnerRoutingTests(unittest.TestCase):
    def test_default_query_reads_all_unread_learning_inbox(self):
        self.assertEqual(DEFAULT_QUERY, "in:inbox is:unread newer_than:30d")

    def test_classifies_youtube_and_github_links_from_email_body(self):
        body = """
        Watch https://www.youtube.com/watch?v=abc123xyz00&feature=share
        Repo: https://github.com/jv813yh/ai-inbox-agent.
        Duplicate: https://youtu.be/abc123xyz00
        """
        links = classify_links(body)

        self.assertEqual(len(links.youtube), 2)
        self.assertIn("https://www.youtube.com/watch?v=abc123xyz00&feature=share", links.youtube)
        self.assertEqual(links.github, ["https://github.com/jv813yh/ai-inbox-agent"])

    def test_classifies_article_links_excluding_youtube_github_and_assets(self):
        body = """
        Read https://example.com/blog/post?utm_source=newsletter#section
        and https://arxiv.org/abs/1234.5678.
        Watch https://www.youtube.com/watch?v=abc123xyz00
        Repo https://github.com/jv813yh/ai-inbox-agent
        Ignore asset https://example.com/pixel.gif and unsubscribe https://newsletter.example.com/unsubscribe?id=1
        """
        links = classify_links(body)

        self.assertIn("https://example.com/blog/post?utm_source=newsletter#section", links.articles)
        self.assertIn("https://arxiv.org/abs/1234.5678", links.articles)
        self.assertFalse(any("youtube" in u or "github.com" in u for u in links.articles))
        self.assertFalse(any("pixel.gif" in u or "unsubscribe" in u for u in links.articles))

    def test_source_ids_are_stable_for_dedupe(self):
        self.assertEqual(source_id_for_youtube_url("https://youtu.be/abc123xyz00?t=12"), "abc123xyz00")
        self.assertEqual(source_id_for_youtube_url("https://youtube.com/watch?feature=share&v=abc123xyz00"), "abc123xyz00")
        self.assertEqual(source_id_for_github_url("https://github.com/jv813yh/ai-inbox-agent/issues/1"), "jv813yh/ai-inbox-agent")

    def test_source_id_for_article_url_strips_tracking_params_and_fragment(self):
        cleaned = source_id_for_article_url("https://example.com/post?utm_source=x&ref=newsletter&id=42#comments")

        self.assertEqual(cleaned, "https://example.com/post?id=42")

    def test_write_daily_personal_ai_news_report_uses_date_hour_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp)
            rel_path = write_daily_personal_ai_news_report(
                notes_dir,
                "🎥 Item → YouTube/Technologie/Channel/item.md",
                run_at=datetime(2026, 7, 4, 19, 5, tzinfo=timezone.utc),
            )
            report = notes_dir / rel_path

            self.assertEqual(rel_path, "Daily Personal AI news/2026-07-04/1905/ai-inbox-agent.md")
            self.assertTrue(report.exists())
            text = report.read_text(encoding="utf-8")
            self.assertIn("category: Daily Personal AI news", text)
            self.assertIn("📬 AI Inbox Agent", text)
            self.assertIn("🎥 Item", text)

    def test_main_saves_daily_personal_ai_news_report_after_successful_index(self):
        from src import server_runner

        class FakeClient:
            marked_read = []

            def __init__(self, token_path):
                self.token_path = token_path

            def search_unread(self, query, *, max_results=5):
                return [GmailMessage(id="msg-ok", thread_id="thread-1", subject="AI", from_addr="sender@example.com", date="today", body="body")]

            def mark_read(self, ids):
                self.marked_read.extend(ids)

        def fake_process_messages(messages, **kwargs):
            return "📰 Article → Web Articles/Technologie/example.com/article.md", ["msg-ok"]

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(server_runner, "GmailApiClient", FakeClient), \
             patch.object(server_runner, "process_messages", side_effect=fake_process_messages), \
             patch.object(server_runner, "index_humanagentwiki", return_value=(True, "indexed")), \
             patch("sys.argv", ["server_runner.py", "--notes-dir", str(Path(tmp) / "notes"), "--humanagentwiki-dir", str(Path(tmp) / "haw")]):
            self.assertEqual(server_runner.main(), 0)
            reports = list((Path(tmp) / "notes" / "Daily Personal AI news").glob("*/*/ai-inbox-agent.md"))
            self.assertEqual(len(reports), 1)
            report_text = reports[0].read_text(encoding="utf-8")

        self.assertEqual(FakeClient.marked_read, ["msg-ok"])
        self.assertIn("📰 Article", report_text)

    def test_dry_run_does_not_create_state_db_or_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes_dir = root / "notes"
            state_db = root / "state" / "processed.sqlite"
            msg = GmailMessage(
                id="msg-1",
                thread_id="thread-1",
                subject="YouTube",
                from_addr="sender@example.com",
                date="today",
                body="https://youtu.be/abc123xyz00",
            )

            digest, successful_ids = process_messages(
                [msg],
                notes_dir=notes_dir,
                state_db=state_db,
                dry_run=True,
            )

            self.assertIn("DRY RUN", digest)
            self.assertEqual(successful_ids, [])
            self.assertFalse(state_db.exists())
            self.assertFalse(notes_dir.exists())

    def test_main_does_not_mark_read_when_index_fails(self):
        from src import server_runner

        class FakeClient:
            marked_read = []

            def __init__(self, token_path):
                self.token_path = token_path

            def search_unread(self, query, *, max_results=5):
                return [
                    GmailMessage(
                        id="msg-index-fail",
                        thread_id="thread-1",
                        subject="YouTube",
                        from_addr="sender@example.com",
                        date="today",
                        body="https://youtu.be/abc123xyz00",
                    )
                ]

            def mark_read(self, ids):
                self.marked_read.extend(ids)

        def fake_process_messages(messages, **kwargs):
            return "digest", ["msg-index-fail"]

        with patch.object(server_runner, "GmailApiClient", FakeClient), \
             patch.object(server_runner, "process_messages", side_effect=fake_process_messages), \
             patch.object(server_runner, "index_humanagentwiki", return_value=(False, "index failed")), \
             patch("sys.argv", ["server_runner.py"]):
            self.assertEqual(server_runner.main(), 0)

        self.assertEqual(FakeClient.marked_read, [])

    def test_process_messages_dedupes_youtube_urls_by_video_id_within_email(self):
        class FakeContentPreparator:
            seen_urls = []

            @staticmethod
            def prepare_youtube_batch(urls, email_body=""):
                FakeContentPreparator.seen_urls = list(urls)
                return [
                    {
                        "url": urls[0],
                        "video_id": "abc123xyz00",
                        "title": "One Video",
                        "channel": "Channel",
                        "summary": "summary",
                        "my_take": "take",
                        "has_full_transcript": True,
                        "transcript_preview": "preview",
                        "processed_at": "2026-07-01T07:00:00+00:00",
                    }
                ]

            @staticmethod
            def prepare_github_batch(urls):
                return []

        with tempfile.TemporaryDirectory() as tmp, patch("src.server_runner._lazy_content_preparator", return_value=FakeContentPreparator):
            root = Path(tmp)
            msg = GmailMessage(
                id="msg-dupe-video",
                thread_id="thread-1",
                subject="YouTube",
                from_addr="sender@example.com",
                date="today",
                body="https://www.youtube.com/watch?v=abc123xyz00&feature=share and https://youtu.be/abc123xyz00",
            )

            digest, successful_ids = process_messages([msg], notes_dir=root / "notes", state_db=root / "state.sqlite")

        self.assertEqual(len(FakeContentPreparator.seen_urls), 1)
        self.assertEqual(successful_ids, ["msg-dupe-video"])
        self.assertIn("One Video", digest)
        self.assertIn("— Channel →", digest)

    def test_process_messages_classifies_youtube_items_before_writing_notes(self):
        class FakeContentPreparator:
            @staticmethod
            def prepare_youtube_batch(urls, email_body=""):
                return [
                    {
                        "url": urls[0],
                        "video_id": "inv123xyz00",
                        "title": "ETF portfolio pre zaciatocnikov",
                        "channel": "Kapitalista",
                        "summary": "summary",
                        "my_take": "take",
                        "has_full_transcript": True,
                        "transcript_preview": "ETF a akcie",
                        "processed_at": "2026-07-01T07:00:00+00:00",
                    }
                ]

            @staticmethod
            def prepare_github_batch(urls):
                return []

        with tempfile.TemporaryDirectory() as tmp, patch("src.server_runner._lazy_content_preparator", return_value=FakeContentPreparator):
            root = Path(tmp)
            msg = GmailMessage(
                id="msg-invest-video",
                thread_id="thread-1",
                subject="YouTube investovanie",
                from_addr="sender@example.com",
                date="today",
                body="https://youtu.be/inv123xyz00",
            )

            digest, successful_ids = process_messages([msg], notes_dir=root / "notes", state_db=root / "state.sqlite")
            notes = list((root / "notes" / "YouTube" / "Investovanie" / "Kapitalista").glob("*.md"))

        self.assertEqual(successful_ids, ["msg-invest-video"])
        self.assertEqual(len(notes), 1)
        self.assertIn("YouTube/Investovanie/Kapitalista/", digest)


    def test_process_messages_routes_article_links_and_writes_notes(self):
        class FakeContentPreparator:
            seen_urls = []

            @staticmethod
            def prepare_youtube_batch(urls, email_body=""):
                return []

            @staticmethod
            def prepare_github_batch(urls):
                return []

            @staticmethod
            def prepare_article_batch(urls, **kwargs):
                FakeContentPreparator.seen_urls = list(urls)
                return [
                    {
                        "type": "web_article",
                        "url": urls[0],
                        "title": "Useful Article",
                        "summary": "Article summary",
                        "my_take": "Useful for backend automation.",
                        "processed_at": "2026-07-04T10:00:00+00:00",
                    }
                ]

        with tempfile.TemporaryDirectory() as tmp, patch("src.server_runner._lazy_content_preparator", return_value=FakeContentPreparator):
            root = Path(tmp)
            msg = GmailMessage(
                id="msg-article",
                thread_id="thread-1",
                subject="Interesting article",
                from_addr="sender@example.com",
                date="today",
                body="Read https://example.com/blog/useful?utm_source=newsletter",
            )

            digest, successful_ids = process_messages([msg], notes_dir=root / "notes", state_db=root / "state.sqlite")
            notes = list((root / "notes" / "Web Articles").glob("*/*/*.md"))

        self.assertEqual(successful_ids, ["msg-article"])
        self.assertEqual(FakeContentPreparator.seen_urls, ["https://example.com/blog/useful?utm_source=newsletter"])
        self.assertEqual(len(notes), 1)
        self.assertIn("Useful Article", digest)


    def test_process_messages_routes_multiple_article_links_from_one_email(self):
        class FakeContentPreparator:
            seen_urls = []

            @staticmethod
            def prepare_youtube_batch(urls, email_body=""):
                return []

            @staticmethod
            def prepare_github_batch(urls):
                return []

            @staticmethod
            def prepare_article_batch(urls, **kwargs):
                FakeContentPreparator.seen_urls = list(urls)
                return [
                    {
                        "type": "web_article",
                        "url": url,
                        "title": f"Article {idx}",
                        "summary": "Useful AI systems article.",
                        "my_take": "Useful for technology learning.",
                        "processed_at": "2026-07-04T10:00:00+00:00",
                    }
                    for idx, url in enumerate(urls, start=1)
                ]

        with tempfile.TemporaryDirectory() as tmp, patch("src.server_runner._lazy_content_preparator", return_value=FakeContentPreparator):
            root = Path(tmp)
            msg = GmailMessage(
                id="msg-many-articles",
                thread_id="thread-1",
                subject="List of links",
                from_addr="sender@example.com",
                date="today",
                body="Read https://example.com/one and https://another.example/two",
            )

            digest, successful_ids = process_messages([msg], notes_dir=root / "notes", state_db=root / "state.sqlite")
            notes = list((root / "notes" / "Web Articles").glob("*/*/*.md"))

        self.assertEqual(successful_ids, ["msg-many-articles"])
        self.assertEqual(len(FakeContentPreparator.seen_urls), 2)
        self.assertEqual(len(notes), 2)
        self.assertIn("Article 1", digest)
        self.assertIn("Article 2", digest)


    def test_process_messages_dedupes_article_links_by_canonical_url(self):
        class FakeContentPreparator:
            called = False

            @staticmethod
            def prepare_youtube_batch(urls, email_body=""):
                return []

            @staticmethod
            def prepare_github_batch(urls):
                return []

            @staticmethod
            def prepare_article_batch(urls, **kwargs):
                FakeContentPreparator.called = True
                return []

        with tempfile.TemporaryDirectory() as tmp, patch("src.server_runner._lazy_content_preparator", return_value=FakeContentPreparator):
            root = Path(tmp)
            state_db = root / "state.sqlite"
            store = StateStore(state_db)
            store.record_source(
                source_type="article",
                source_id="https://example.com/blog/useful?id=42",
                source_url="https://example.com/blog/useful?id=42",
                note_path="Web Articles/example-com/existing.md",
                first_seen_message_id="old-msg",
            )
            msg = GmailMessage(
                id="msg-article-dupe",
                thread_id="thread-1",
                subject="Duplicate article",
                from_addr="sender@example.com",
                date="today",
                body="Read https://example.com/blog/useful?id=42&utm_source=newsletter#top",
            )

            digest, successful_ids = process_messages([msg], notes_dir=root / "notes", state_db=state_db)

        self.assertEqual(successful_ids, ["msg-article-dupe"])
        self.assertFalse(FakeContentPreparator.called)
        self.assertIn("skipped duplicate", digest.lower())

    def test_process_messages_already_state_recorded_unread_email_is_returned_for_mark_read_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_db = root / "state.sqlite"
            store = StateStore(state_db)
            store.record_message(
                gmail_account="learning",
                gmail_message_id="msg-already-processed",
                thread_id="thread-1",
                subject="Already processed but unread",
                from_addr="sender@example.com",
                status="processed",
            )
            msg = GmailMessage(
                id="msg-already-processed",
                thread_id="thread-1",
                subject="Already processed but unread",
                from_addr="sender@example.com",
                date="today",
                body="https://example.com/blog/useful",
            )

            digest, successful_ids = process_messages([msg], notes_dir=root / "notes", state_db=state_db)

        self.assertEqual(successful_ids, ["msg-already-processed"])
        self.assertIn("already handled email", digest.lower())

    def test_process_messages_records_failed_link_processing_to_avoid_infinite_retry(self):
        class FakeContentPreparator:
            @staticmethod
            def prepare_youtube_batch(urls, email_body=""):
                return []

            @staticmethod
            def prepare_github_batch(urls):
                return []

            @staticmethod
            def prepare_article_batch(urls, **kwargs):
                return []

        with tempfile.TemporaryDirectory() as tmp, patch("src.server_runner._lazy_content_preparator", return_value=FakeContentPreparator):
            root = Path(tmp)
            state_db = root / "state.sqlite"
            store = StateStore(state_db)
            msg = GmailMessage(
                id="msg-article-fail",
                thread_id="thread-1",
                subject="Broken article",
                from_addr="sender@example.com",
                date="today",
                body="Read https://example.com/broken-article",
            )

            digest, successful_ids = process_messages([msg], notes_dir=root / "notes", state_db=state_db)
            with store._connect() as conn:
                row = conn.execute(
                    "select status from processed_messages where gmail_account=? and gmail_message_id=?",
                    ("learning", "msg-article-fail"),
                ).fetchone()

        self.assertEqual(successful_ids, ["msg-article-fail"])
        self.assertEqual(row[0], "skipped_failed_processing")
        self.assertIn("failed processing", digest.lower())

    def test_process_messages_short_no_link_email_records_skipped_unclassified_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_db = root / "state.sqlite"
            store = StateStore(state_db)
            msg = GmailMessage(
                id="msg-short",
                thread_id="thread-1",
                subject="Short misc email",
                from_addr="sender@example.com",
                date="today",
                body="ok",
            )

            digest, successful_ids = process_messages([msg], notes_dir=root / "notes", state_db=state_db)
            with store._connect() as conn:
                row = conn.execute(
                    "select status from processed_messages where gmail_account=? and gmail_message_id=?",
                    ("learning", "msg-short"),
                ).fetchone()

        self.assertEqual(successful_ids, ["msg-short"])
        self.assertEqual(row[0], "skipped_unclassified")
        self.assertIn("Skipped unclassified", digest)

    def test_process_messages_plain_email_processed_when_enabled(self):
        class FakeContentPreparator:
            @staticmethod
            def prepare_plain_email(subject, from_addr, body):
                return {
                    "type": "plain_email",
                    "subject": subject,
                    "from_addr": from_addr,
                    "summary": "Email summary",
                    "my_take": "Follow up later.",
                    "processed_at": "2026-07-04T10:00:00+00:00",
                }

        with tempfile.TemporaryDirectory() as tmp, patch("src.server_runner._lazy_content_preparator", return_value=FakeContentPreparator):
            root = Path(tmp)
            msg = GmailMessage(
                id="msg-plain-enabled",
                thread_id="thread-1",
                subject="Long useful email",
                from_addr="sender@example.com",
                date="today",
                body="This is a long useful email about AI systems. " * 20,
            )

            digest, successful_ids = process_messages(
                [msg], notes_dir=root / "notes", state_db=root / "state.sqlite", include_plain_emails=True
            )
            notes = list((root / "notes" / "Emails").glob("*/*/*.md"))

        self.assertEqual(successful_ids, ["msg-plain-enabled"])
        self.assertEqual(len(notes), 1)
        self.assertIn("Long useful email", digest)

    def test_process_messages_records_failed_plain_email_processing_to_avoid_infinite_retry(self):
        class FakeContentPreparator:
            @staticmethod
            def prepare_plain_email(subject, from_addr, body):
                return None

        with tempfile.TemporaryDirectory() as tmp, patch("src.server_runner._lazy_content_preparator", return_value=FakeContentPreparator):
            root = Path(tmp)
            state_db = root / "state.sqlite"
            store = StateStore(state_db)
            msg = GmailMessage(
                id="msg-plain-fail",
                thread_id="thread-1",
                subject="Long useful email",
                from_addr="sender@example.com",
                date="today",
                body="This is a long useful email about AI systems. " * 20,
            )

            digest, successful_ids = process_messages(
                [msg], notes_dir=root / "notes", state_db=state_db, include_plain_emails=True
            )
            with store._connect() as conn:
                row = conn.execute(
                    "select status from processed_messages where gmail_account=? and gmail_message_id=?",
                    ("learning", "msg-plain-fail"),
                ).fetchone()

        self.assertEqual(successful_ids, ["msg-plain-fail"])
        self.assertEqual(row[0], "skipped_failed_processing")
        self.assertIn("failed processing", digest.lower())

    def test_process_messages_marks_duplicate_only_email_successful_with_skipped_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_db = root / "state.sqlite"
            store = StateStore(state_db)
            store.record_source(
                source_type="youtube",
                source_id="abc123xyz00",
                source_url="https://youtu.be/abc123xyz00",
                note_path="Videos/existing.md",
                first_seen_message_id="old-msg",
            )
            msg = GmailMessage(
                id="duplicate-msg",
                thread_id="thread-1",
                subject="Already saw this",
                from_addr="sender@example.com",
                date="today",
                body="https://youtu.be/abc123xyz00",
            )

            digest, successful_ids = process_messages([msg], notes_dir=root / "notes", state_db=state_db)

            with store._connect() as conn:
                row = conn.execute(
                    "select status from processed_messages where gmail_account=? and gmail_message_id=?",
                    ("learning", "duplicate-msg"),
                ).fetchone()

        self.assertEqual(successful_ids, ["duplicate-msg"])
        self.assertEqual(row[0], "skipped_duplicate")
        self.assertIn("skipped duplicate", digest.lower())


if __name__ == "__main__":
    unittest.main()
