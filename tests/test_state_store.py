import tempfile
import unittest
from pathlib import Path

from src.state_store import StateStore


class StateStoreTests(unittest.TestCase):
    def test_records_processed_messages_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite"
            store = StateStore(db_path)

            self.assertFalse(store.is_message_processed("learning", "msg-1"))

            store.record_message(
                gmail_account="learning",
                gmail_message_id="msg-1",
                thread_id="thread-1",
                subject="YouTube video",
                from_addr="sender@example.com",
                status="processed",
            )

            self.assertTrue(store.is_message_processed("learning", "msg-1"))
            store.record_message(
                gmail_account="learning",
                gmail_message_id="msg-1",
                thread_id="thread-1b",
                subject="Updated subject",
                from_addr="sender2@example.com",
                status="processed",
            )
            self.assertEqual(store.count_messages(), 1)

    def test_records_processed_sources_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite"
            store = StateStore(db_path)

            self.assertFalse(store.is_source_processed("youtube", "abc123"))

            store.record_source(
                source_type="youtube",
                source_id="abc123",
                source_url="https://youtu.be/abc123",
                note_path="Videos/abc123.md",
                first_seen_message_id="msg-1",
            )

            self.assertTrue(store.is_source_processed("youtube", "abc123"))
            self.assertEqual(store.get_source_note_path("youtube", "abc123"), "Videos/abc123.md")

            store.record_source(
                source_type="youtube",
                source_id="abc123",
                source_url="https://youtube.com/watch?v=abc123",
                note_path="Videos/abc123-new.md",
                first_seen_message_id="msg-2",
            )
            self.assertEqual(store.count_sources(), 1)
            self.assertEqual(store.get_source_note_path("youtube", "abc123"), "Videos/abc123-new.md")


if __name__ == "__main__":
    unittest.main()
