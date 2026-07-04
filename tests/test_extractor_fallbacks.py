import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from extractors_full import GitHubExtractor


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
        self.assertIn("Fallback summary", summary["summary"])
        self.assertEqual(summary["owner"], "jv813yh")
        self.assertEqual(summary["repo"], "ai-inbox-agent")


if __name__ == "__main__":
    unittest.main()
