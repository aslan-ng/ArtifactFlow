import unittest
from dataclasses import FrozenInstanceError

from artifactflow import Artifact, Plan, Tool
from artifactflow.advisor import (
    AdvisedOption,
    AdviceHistory,
    AdviceSnapshot,
)


def make_plan(*tool_names: str) -> Plan:
    plan = Plan()
    previous = Artifact("start")
    for index, tool_name in enumerate(tool_names):
        following = Artifact(f"artifact {index}")
        plan.add_tool(
            Tool(tool_name, inputs=[previous], outputs=[following])
        )
        previous = following
    plan.starting_artifacts = ["start"]
    plan.target_artifacts = [previous.name]
    return plan


class TestAdviceSnapshot(unittest.TestCase):
    def test_keeps_visible_tools_and_small_plan_signatures(self):
        shared = make_plan("Prepare", "Quick")
        longer = make_plan("Prepare", "Custom", "Finish")

        snapshot = AdviceSnapshot.create(
            event_position=0,
            configuration=(2, 3, 0.5),
            visible_root_tools=["Prepare"],
            supporting_plans={"Prepare": [shared, longer]},
        )

        self.assertEqual(snapshot.visible_root_tools, ("Prepare",))
        self.assertEqual(
            snapshot.plans_for("Prepare"),
            (
                ("Prepare", "Quick"),
                ("Prepare", "Custom", "Finish"),
            ),
        )
        self.assertEqual(snapshot.plans_for("unknown"), ())
        with self.assertRaises(FrozenInstanceError):
            snapshot.event_position = 1  # type: ignore[misc]

    def test_rejects_support_for_a_tool_that_was_not_shown(self):
        with self.assertRaisesRegex(ValueError, "not visible"):
            AdviceSnapshot.create(
                event_position=0,
                configuration="default",
                visible_root_tools=["A"],
                supporting_plans={"B": [make_plan("B")]},
            )

    def test_distinguishes_the_same_tool_at_two_artifact_versions(self):
        older = AdvisedOption(
            tool_name="Analyze",
            input_artifacts=(("Dataset", 1),),
            supporting_plan_signatures=(("Prepare", "Analyze"),),
        )
        newer = AdvisedOption(
            tool_name="Analyze",
            input_artifacts=(("Dataset", 2),),
            supporting_plan_signatures=(("Refresh", "Analyze"),),
        )

        snapshot = AdviceSnapshot.create(
            event_position=3,
            configuration="default",
            options=(older, newer),
        )

        self.assertEqual(
            snapshot.visible_root_tools,
            ("Analyze", "Analyze"),
        )
        self.assertIs(
            snapshot.option_for("Analyze", (("Dataset", 1),)),
            older,
        )
        self.assertIs(
            snapshot.option_for("Analyze", (("Dataset", 2),)),
            newer,
        )
        self.assertEqual(
            snapshot.plans_for("Analyze", (("Dataset", 1),)),
            (("Prepare", "Analyze"),),
        )
        self.assertEqual(
            snapshot.plans_for("Analyze", (("Dataset", 2),)),
            (("Refresh", "Analyze"),),
        )
        self.assertEqual(
            snapshot.plans_for("Analyze"),
            (
                ("Prepare", "Analyze"),
                ("Refresh", "Analyze"),
            ),
        )

    def test_rejects_duplicate_exact_option_identity(self):
        option = AdvisedOption(
            "Analyze",
            (("Dataset", 1),),
        )

        with self.assertRaisesRegex(ValueError, "unique tool/input"):
            AdviceSnapshot.create(
                event_position=0,
                configuration="default",
                options=(option, option),
            )

    def test_deduplicates_repeated_supporting_plan_signatures(self):
        signature = ("Prepare", "Analyze")

        option = AdvisedOption(
            "Analyze",
            supporting_plan_signatures=(signature, signature),
        )

        self.assertEqual(option.supporting_plan_signatures, (signature,))


class TestAdviceHistory(unittest.TestCase):
    def test_repeated_advice_reuses_snapshot_when_nothing_changed(self):
        history = AdviceHistory()
        plan = make_plan("A")

        first = history.record(
            event_position=0,
            configuration=(1, None, 1.0),
            visible_root_tools=["A"],
            supporting_plans={"A": [plan]},
        )
        repeated = history.record(
            event_position=0,
            configuration=(1, None, 1.0),
            visible_root_tools=["A"],
            supporting_plans={"A": [plan]},
        )

        self.assertIs(repeated, first)
        self.assertEqual(len(history), 1)
        self.assertEqual(history.snapshots, (first,))

    def test_same_position_allows_distinct_configurations(self):
        history = AdviceHistory()

        narrow = history.record(
            event_position=2,
            configuration=(1, 1, 1.0),
            visible_root_tools=["A"],
        )
        broad = history.record(
            event_position=2,
            configuration=(2, None, 1.0),
            visible_root_tools=["A", "B"],
        )

        self.assertEqual(len(history), 2)
        self.assertIs(history.get(2, narrow.configuration), narrow)
        self.assertIs(history.get(2, broad.configuration), broad)

    def test_reused_snapshot_becomes_the_most_recent_issuance(self):
        history = AdviceHistory()
        normative = history.record(
            event_position=2,
            configuration="normative",
            visible_root_tools=["Restore"],
        )
        homophilic = history.record(
            event_position=2,
            configuration="homophilic",
            visible_root_tools=["Continue"],
        )

        repeated_normative = history.record(
            event_position=2,
            configuration="normative",
            visible_root_tools=["Restore"],
        )

        self.assertIs(repeated_normative, normative)
        self.assertIsNot(normative, homophilic)
        self.assertEqual(len(history), 2)
        self.assertEqual(history.snapshots, (normative, homophilic))
        self.assertIs(history.latest(), normative)
        self.assertIs(history.latest_before(3), normative)
        self.assertIs(history.latest("homophilic"), homophilic)

    def test_none_can_be_used_as_an_explicit_configuration(self):
        history = AdviceHistory()
        none_config = history.record(
            event_position=0,
            configuration=None,
            visible_root_tools=["A"],
        )
        history.record(
            event_position=1,
            configuration="other",
            visible_root_tools=["B"],
        )

        self.assertIs(history.latest(None), none_config)

    def test_conflicting_advice_for_same_state_and_config_is_rejected(self):
        history = AdviceHistory()
        history.record(
            event_position=0,
            configuration="default",
            visible_root_tools=["A"],
        )

        with self.assertRaisesRegex(ValueError, "Different advice"):
            history.record(
                event_position=0,
                configuration="default",
                visible_root_tools=["B"],
            )

    def test_record_accepts_and_reuses_exact_options(self):
        history = AdviceHistory()
        options = (
            AdvisedOption("Analyze", (("Dataset", 1),)),
            AdvisedOption("Analyze", (("Dataset", 2),)),
        )

        first = history.record(
            event_position=2,
            configuration="default",
            options=options,
        )
        repeated = history.record(
            event_position=2,
            configuration="default",
            options=options,
        )

        self.assertIs(repeated, first)
        self.assertEqual(first.options, options)
        self.assertEqual(len(history), 1)

    def test_exact_binding_change_is_conflicting_advice(self):
        history = AdviceHistory()
        history.record(
            event_position=2,
            configuration="default",
            options=(
                AdvisedOption("Analyze", (("Dataset", 1),)),
            ),
        )

        with self.assertRaisesRegex(ValueError, "Different advice"):
            history.record(
                event_position=2,
                configuration="default",
                options=(
                    AdvisedOption("Analyze", (("Dataset", 2),)),
                ),
            )

    def test_exact_and_legacy_option_arguments_cannot_be_mixed(self):
        history = AdviceHistory()

        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            history.record(
                event_position=0,
                configuration="default",
                visible_root_tools=["Analyze"],
                options=(AdvisedOption("Analyze"),),
            )

    def test_latest_before_is_strict_and_can_filter_configuration(self):
        history = AdviceHistory()
        first = history.record(
            event_position=0,
            configuration="normative",
            visible_root_tools=["A"],
        )
        history.record(
            event_position=1,
            configuration="homophilic",
            visible_root_tools=["X"],
        )
        second = history.record(
            event_position=2,
            configuration="normative",
            visible_root_tools=["B"],
        )

        self.assertIsNone(history.latest_before(0))
        self.assertIs(history.latest_before(1), first)
        self.assertIs(
            history.latest_before(2, "normative"),
            first,
        )
        self.assertIs(
            history.latest_before(3, "normative"),
            second,
        )
        self.assertIs(history.latest("normative"), second)

    def test_rejects_invalid_positions_and_unhashable_configuration(self):
        history = AdviceHistory()

        with self.assertRaisesRegex(ValueError, "negative"):
            history.record(
                event_position=-1,
                configuration="default",
            )
        with self.assertRaisesRegex(TypeError, "hashable"):
            history.record(
                event_position=0,
                configuration=[],  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
