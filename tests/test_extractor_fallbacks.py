import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from extractors_full import GitHubExtractor, YouTubeExtractor, ContentPreparator


class ExtractorFallbackTests(unittest.TestCase):
    def test_extractors_full_imports_as_package_module(self):
        repo = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [str(repo / ".venv" / "bin" / "python"), "-c", "import src.extractors_full; print('IMPORT_OK')"],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("IMPORT_OK", proc.stdout)

    def test_github_summary_falls_back_when_claude_fails(self):
        repo_info = {
            "owner": "jv813yh",
            "repo": "ai-inbox-agent",
            "url": "https://github.com/jv813yh/ai-inbox-agent",
            "description": "Email AI agent",
            "stars": 7,
            "forks": 1,
            "language": "Python",
            "topics": ["gmail", "agents"],
            "readme": "# ai-inbox-agent\nReads inbox links.",
        }

        with patch("extractors_full.client.messages.create", side_effect=RuntimeError("no api key")):
            summary = GitHubExtractor.summarize_repo(repo_info)

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["type"], "github_repo")
        self.assertIn("GitHub metadata fallback", summary["summary"])
        self.assertIn("HOW JOZEF COULD USE THIS", summary["summary"])
        self.assertNotIn("Open the repository and review the README/source", summary["summary"])
        self.assertIn("implementation patterns", summary["summary"])
        self.assertEqual(summary["owner"], "jv813yh")
        self.assertEqual(summary["repo"], "ai-inbox-agent")

    def test_youtube_info_uses_oembed_when_ytdlp_is_blocked(self):
        class FakeResponse:
            status_code = 200
            def json(self):
                return {
                    "title": "Prompting 101 | Code w/ Claude",
                    "author_name": "Anthropic",
                    "thumbnail_url": "https://img.example/thumb.jpg",
                }

        with patch("extractors_full.YoutubeDL", side_effect=RuntimeError("blocked")), \
             patch("extractors_full.requests.get", return_value=FakeResponse()):
            info = YouTubeExtractor.get_video_info("https://youtu.be/ysPbXH0LpIE")

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info["channel"], "Anthropic")
        self.assertEqual(info["title"], "Prompting 101 | Code w/ Claude")
        self.assertEqual(info["video_id"], "ysPbXH0LpIE")

    def test_youtube_info_parses_channel_from_watch_page_when_oembed_missing(self):
        class FakeResponse:
            def __init__(self, status_code, text="", payload=None):
                self.status_code = status_code
                self.text = text
                self._payload = payload or {}
            def json(self):
                return self._payload

        html = '''<html><head><meta property="og:title" content="Watch Page Title"></head><body>
        {"ownerChannelName":"Real Channel From Page","externalChannelId":"UC123"}
        </body></html>'''
        with patch("extractors_full.YoutubeDL", side_effect=RuntimeError("blocked")), \
             patch("extractors_full.requests.get", side_effect=[FakeResponse(404), FakeResponse(200, text=html)]):
            info = YouTubeExtractor.get_video_info("https://youtu.be/ysPbXH0LpIE")

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info["channel"], "Real Channel From Page")
        self.assertEqual(info["title"], "Watch Page Title")

    def test_youtube_transcript_api_v1_fetch_uses_language_fallbacks(self):
        class FakeFetchedItem:
            def __init__(self, text):
                self.text = text

        class FakeTranscriptApi:
            calls = []
            def fetch(self, video_id, languages=("en",), preserve_formatting=False):
                FakeTranscriptApi.calls.append((video_id, tuple(languages), preserve_formatting))
                return [FakeFetchedItem("hello"), FakeFetchedItem("world")]

        with patch.object(YouTubeExtractor, "_get_transcript_via_ytdlp", return_value=None), \
             patch("extractors_full.YouTubeTranscriptApi", return_value=FakeTranscriptApi()):
            transcript = YouTubeExtractor.get_transcript("https://youtu.be/abc123xyz00")

        self.assertEqual(transcript, "hello world")
        self.assertEqual(FakeTranscriptApi.calls, [("abc123xyz00", ("en", "en-US", "en-GB", "a.en"), False)])

    def test_youtube_transcript_api_v1_fetch_handles_raw_dict_items(self):
        class FakeTranscriptApi:
            def fetch(self, video_id, languages=("en",), preserve_formatting=False):
                return [{"text": "dict"}, {"text": "items"}]

        with patch.object(YouTubeExtractor, "_get_transcript_via_ytdlp", return_value=None), \
             patch("extractors_full.YouTubeTranscriptApi", return_value=FakeTranscriptApi()):
            transcript = YouTubeExtractor.get_transcript("https://youtu.be/abc123xyz00")

        self.assertEqual(transcript, "dict items")

    def test_prepare_youtube_batch_preserves_channel_metadata(self):
        with patch.object(YouTubeExtractor, "get_video_info", return_value={
            "url": "https://youtu.be/abc123xyz00",
            "video_id": "abc123xyz00",
            "title": "Agent Video",
            "description": "",
            "channel": "Agent Lab",
        }), patch.object(YouTubeExtractor, "get_transcript", return_value="transcript"), \
           patch.object(YouTubeExtractor, "summarize_video", return_value={
               "type": "youtube_video",
               "url": "https://youtu.be/abc123xyz00",
               "title": "Agent Video",
               "summary": "summary",
               "my_take": "take",
           }):
            items = ContentPreparator.prepare_youtube_batch(["https://youtu.be/abc123xyz00"])

        self.assertEqual(items[0]["channel"], "Agent Lab")
        self.assertEqual(items[0]["video_id"], "abc123xyz00")


if __name__ == "__main__":
    unittest.main()
