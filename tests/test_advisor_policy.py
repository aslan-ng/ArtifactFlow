import unittest

from artifactflow.advisor import (
    BALANCED,
    CandidateScope,
    CandidateTransition,
    GuidancePolicy,
    OPPORTUNISTIC,
    WORKFLOW_ADHERENT,
)


class TestGuidancePolicy(unittest.TestCase):
    def test_continuity_weight_complements_workflow_adherence(self):
        policy = GuidancePolicy(workflow_adherence=0.25)

        self.assertEqual(policy.workflow_adherence, 0.25)
        self.assertEqual(policy.continuity_weight, 0.75)

    def test_policy_is_immutable(self):
        policy = GuidancePolicy()

        with self.assertRaises(AttributeError):
            policy.workflow_adherence = 0.5  # type: ignore[misc]

    def test_workflow_adherence_must_be_finite_and_in_range(self):
        for invalid in (-0.01, 1.01, float("nan"), float("inf")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    GuidancePolicy(workflow_adherence=invalid)

        for invalid in (True, "0.5", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    GuidancePolicy(  # type: ignore[arg-type]
                        workflow_adherence=invalid
                    )

    def test_presets_cover_the_policy_range(self):
        self.assertEqual(WORKFLOW_ADHERENT.workflow_adherence, 1.0)
        self.assertEqual(BALANCED.workflow_adherence, 0.5)
        self.assertEqual(OPPORTUNISTIC.workflow_adherence, 0.0)

    def test_workflow_adherent_policy_prefers_the_proposed_plan(self):
        restore_proposal = WORKFLOW_ADHERENT.cost(
            CandidateScope.PROPOSED_PLAN,
            CandidateTransition.RESTORE_CHECKPOINT,
        )
        continue_deviation = WORKFLOW_ADHERENT.cost(
            CandidateScope.TOOL_NETWORK,
            CandidateTransition.CONTINUE_CURRENT,
        )

        self.assertLess(restore_proposal, continue_deviation)

    def test_opportunistic_policy_prefers_current_direction(self):
        restore_proposal = OPPORTUNISTIC.cost(
            CandidateScope.PROPOSED_PLAN,
            CandidateTransition.RESTORE_CHECKPOINT,
        )
        continue_deviation = OPPORTUNISTIC.cost(
            CandidateScope.TOOL_NETWORK,
            CandidateTransition.CONTINUE_CURRENT,
        )

        self.assertGreater(restore_proposal, continue_deviation)

    def test_balanced_policy_gives_both_dimensions_equal_weight(self):
        restore_proposal = BALANCED.cost(
            CandidateScope.PROPOSED_PLAN,
            CandidateTransition.RESTORE_CHECKPOINT,
        )
        continue_deviation = BALANCED.cost(
            CandidateScope.TOOL_NETWORK,
            CandidateTransition.CONTINUE_CURRENT,
        )

        self.assertEqual(restore_proposal, continue_deviation)

    def test_rank_uses_simple_deterministic_tie_breakers(self):
        policy = GuidancePolicy(workflow_adherence=0.5)

        def rank(**tie_breakers: int) -> tuple[float, int, int, int]:
            return policy.rank(
                CandidateScope.WORKFLOW_PLAN,
                CandidateTransition.REJOIN,
                **tie_breakers,
            )

        ready = rank(missing_artifacts=0)
        missing = rank(missing_artifacts=1)
        shorter = rank(remaining_tools=1)
        longer = rank(remaining_tools=2)
        earlier = rank(stable_order=1)
        later = rank(stable_order=2)

        self.assertLess(ready, missing)
        self.assertLess(shorter, longer)
        self.assertLess(earlier, later)

    def test_rank_rejects_invalid_tie_breakers(self):
        policy = GuidancePolicy()

        with self.assertRaises(TypeError):
            policy.rank(
                CandidateScope.PROPOSED_PLAN,
                CandidateTransition.CONTINUE_CURRENT,
                missing_artifacts=True,
            )
        with self.assertRaises(ValueError):
            policy.rank(
                CandidateScope.PROPOSED_PLAN,
                CandidateTransition.CONTINUE_CURRENT,
                remaining_tools=-1,
            )

    def test_cost_requires_explicit_candidate_categories(self):
        policy = GuidancePolicy()

        with self.assertRaises(TypeError):
            policy.cost(
                0,  # type: ignore[arg-type]
                CandidateTransition.CONTINUE_CURRENT,
            )
        with self.assertRaises(TypeError):
            policy.cost(CandidateScope.PROPOSED_PLAN, 0)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
