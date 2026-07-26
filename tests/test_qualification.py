import unittest

from pr_hunter.qualification import evaluate_qualification


class QualificationTests(unittest.TestCase):
    def test_ready_only_with_full_evidence_and_positive_signal(self):
        result = evaluate_qualification(
            "owner/repo#1",
            reproduced=True,
            root_cause_confidence="high",
            test_plan=True,
            ci_feasible=True,
            scope="medium",
            maintainer_signal="positive",
        )
        self.assertEqual(result.readiness, "ready_to_claim")
        self.assertEqual(result.blockers, ())

    def test_unknown_maintainer_requires_contact(self):
        result = evaluate_qualification(
            "owner/repo#1",
            reproduced=True,
            root_cause_confidence="high",
            test_plan=True,
            ci_feasible=True,
            scope="small",
            maintainer_signal="unknown",
        )
        self.assertEqual(result.readiness, "ask_maintainer")

    def test_plausible_root_cause_cannot_pass(self):
        result = evaluate_qualification(
            "owner/repo#1",
            reproduced=True,
            root_cause_confidence="medium",
            test_plan=True,
            ci_feasible=True,
            scope="medium",
            maintainer_signal="positive",
        )
        self.assertEqual(result.readiness, "do_not_start")
        self.assertTrue(any("Root cause" in blocker for blocker in result.blockers))


if __name__ == "__main__":
    unittest.main()
