import unittest

from pr_hunter.ai import AIReviewError, _extract_json


class AIParsingTests(unittest.TestCase):
    def test_extracts_fenced_json(self):
        value = _extract_json('```json\n{"verdict":"veto"}\n```')
        self.assertEqual(value["verdict"], "veto")

    def test_extracts_json_from_short_preamble(self):
        value = _extract_json('Result:\n{"recommendation":"skip"}')
        self.assertEqual(value["recommendation"], "skip")

    def test_rejects_non_json(self):
        with self.assertRaises(AIReviewError):
            _extract_json("This issue looks fine.")


if __name__ == "__main__":
    unittest.main()
