from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pr_hunter.config import load_config


class ConfigTests(unittest.TestCase):
    def test_relative_state_path_is_relative_to_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "hunter.toml"
            config_path.write_text(
                """
[profile]
languages = ["Go"]

[scan]
state_path = "var/hunter.db"
queries = ["is:issue is:open"]
""".strip()
            )
            config = load_config(config_path)
            self.assertEqual(config.profile.languages, ("Go",))
            self.assertEqual(
                config.scan.state_path,
                (Path(directory) / "var/hunter.db").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
