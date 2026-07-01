import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.gmail_api_client import GmailMessage
from src.server_runner import classify_links, process_messages, source_id_for_github_url, source_id_for_youtube_url
from src.state_store import StateStore


class ServerRunnerRoutingTests(unittest.TestCase):
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

    def test_source_ids_are_stable_for_dedupe(self):
        self.assertEqual(source_id_for_youtube_url("https://youtu.be/abc123xyz00?t=12"), "abc123xyz00")
        self.assertEqual(source_id_for_youtube_url("https://youtube.com/watch?feature=share&v=abc123xyz00"), "abc123xyz00")
        self.assertEqual(source_id_for_github_url("https://github.com/jv813yh/ai-inbox-agent/issues/1"), "jv813yh/ai-inbox-agent")
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
