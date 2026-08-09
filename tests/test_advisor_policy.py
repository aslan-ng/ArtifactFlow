import unittest

from artifactflow.advisor import (
    AdvisorCharacter,
    BALANCED,
    CandidateScope,
    CandidateTransition,
    HOMOPHILIC,
    NORMATIVE,
)


class TestAdvisorCharacter(unittest.TestCase):
    def test_homophily_is_complement_of_normativity(self):
        character = AdvisorCharacter(normativity=0.25)

        self.assertEqual(character.normativity, 0.25)
        self.assertEqual(character.homophily, 0.75)

    def test_character_is_immutable(self):
        character = AdvisorCharacter()

        with self.assertRaises(AttributeError):
            character.normativity = 0.5  # type: ignore[misc]

    def test_normativity_must_be_finite_and_between_zero_and_one(self):
        for invalid in (-0.01, 1.01, float("nan"), float("inf")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    AdvisorCharacter(normativity=invalid)

        for invalid in (True, "0.5", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    AdvisorCharacter(normativity=invalid)  # type: ignore[arg-type]

    def test_presets_cover_the_character_range(self):
        self.assertEqual(NORMATIVE.normativity, 1.0)
        self.assertEqual(BALANCED.normativity, 0.5)
        self.assertEqual(HOMOPHILIC.normativity, 0.0)

    def test_normative_character_prefers_the_proposed_plan(self):
        restore_proposal = NORMATIVE.cost(
            CandidateScope.PROPOSED_PLAN,
            CandidateTransition.RESTORE_CHECKPOINT,
        )
        continue_deviation = NORMATIVE.cost(
            CandidateScope.TOOL_NETWORK,
            CandidateTransition.CONTINUE_CURRENT,
        )

        self.assertLess(restore_proposal, continue_deviation)

    def test_homophilic_character_prefers_continuing_current_direction(self):
        restore_proposal = HOMOPHILIC.cost(
            CandidateScope.PROPOSED_PLAN,
            CandidateTransition.RESTORE_CHECKPOINT,
        )
        continue_deviation = HOMOPHILIC.cost(
            CandidateScope.TOOL_NETWORK,
            CandidateTransition.CONTINUE_CURRENT,
        )

        self.assertGreater(restore_proposal, continue_deviation)

    def test_balanced_character_gives_both_dimensions_equal_weight(self):
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
        character = AdvisorCharacter(normativity=0.5)

        def rank(**tie_breakers: int) -> tuple[float, int, int, int]:
            return character.rank(
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
        character = AdvisorCharacter()

        with self.assertRaises(TypeError):
            character.rank(
                CandidateScope.PROPOSED_PLAN,
                CandidateTransition.CONTINUE_CURRENT,
                missing_artifacts=True,
            )
        with self.assertRaises(ValueError):
            character.rank(
                CandidateScope.PROPOSED_PLAN,
                CandidateTransition.CONTINUE_CURRENT,
                remaining_tools=-1,
            )

    def test_cost_requires_explicit_candidate_categories(self):
        character = AdvisorCharacter()

        with self.assertRaises(TypeError):
            character.cost(
                0,  # type: ignore[arg-type]
                CandidateTransition.CONTINUE_CURRENT,
            )
        with self.assertRaises(TypeError):
            character.cost(CandidateScope.PROPOSED_PLAN, 0)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
