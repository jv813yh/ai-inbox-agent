import tempfile
import unittest
from pathlib import Path

from src.server_runner import load_env_file


class HumanAgentWikiEnvTests(unittest.TestCase):
    def test_load_env_file_parses_embedding_settings_without_overwriting_existing_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "# comment\n"
                "EMBED_MODEL=intfloat/multilingual-e5-small\n"
                "EMBED_DIM=384\n"
                "QUOTED=\"hello world\"\n"
                "EMPTY=\n",
                encoding="utf-8",
            )

            parsed = load_env_file(env_path)

            self.assertEqual(parsed["EMBED_MODEL"], "intfloat/multilingual-e5-small")
            self.assertEqual(parsed["EMBED_DIM"], "384")
            self.assertEqual(parsed["QUOTED"], "hello world")
            self.assertEqual(parsed["EMPTY"], "")


if __name__ == "__main__":
    unittest.main()
