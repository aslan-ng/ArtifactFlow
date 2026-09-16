import unittest
from unittest.mock import patch

from artifactflow import (
    AdvisedOption,
    Advisor,
    Artifact,
    OPPORTUNISTIC,
    Plan,
    Project,
    Tool,
    Workflow,
)


def make_workflow(
    *tools: Tool,
    starting: tuple[str, ...],
    target: tuple[str, ...] = ("target",),
) -> Workflow:
    workflow = Workflow()
    for tool in tools:
        workflow.add_tool(tool)
    workflow.starting_artifacts = list(starting)
    workflow.target_artifacts = list(target)
    return workflow


def option_names(command) -> tuple[str, ...]:
    return tuple(option.tool_name for option in command.options)


class TestMeaningfulLongerRoutes(unittest.TestCase):
    def test_optional_refinement_route_is_not_pruned_by_the_shorter_route(
        self,
    ):
        start = Artifact("start")
        prepared = Artifact("prepared")
        draft = Artifact("draft")
        publishable = Artifact("publishable")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("One", inputs=[start], outputs=[prepared]),
            Tool(
                "Two",
                inputs=[prepared],
                outputs=[draft, publishable],
            ),
            Tool("Three", inputs=[publishable], outputs=[target]),
            Tool("Four", inputs=[draft], outputs=[publishable]),
            starting=("start",),
        )

        plans = {
            tuple(plan.tool_names): plan
            for plan in workflow.discover_plans()
        }
        self.assertEqual(
            set(plans),
            {
                ("One", "Two", "Three"),
                ("One", "Two", "Three", "Four"),
            },
        )
        self.assertEqual(
            plans[("One", "Two", "Three")].producers_for_input(
                "Three",
                "publishable",
            ),
            ("Two",),
        )
        self.assertEqual(
            plans[("One", "Two", "Three", "Four")]
            .producers_for_input("Three", "publishable"),
            ("Four",),
        )

        preview = Advisor(
            Project(workflow),
            lookahead_depth=3,
            max_options=3,
        ).advise()
        self.assertEqual(option_names(preview), ("One",))
        after_one = preview.options[0].continuations
        self.assertEqual(
            tuple(option.tool_name for option in after_one),
            ("Two",),
        )
        self.assertEqual(
            tuple(
                option.tool_name
                for option in after_one[0].continuations
            ),
            ("Three", "Four"),
        )

        project = Project(workflow)
        advisor = Advisor(project, max_options=3)
        project.record_tool_success("One")
        project.record_tool_success("Two")

        decision = advisor.advise()
        self.assertEqual(option_names(decision), ("Three", "Four"))

        project.record_tool_success("Four")
        narrowed = advisor.advise()

        self.assertEqual(option_names(narrowed), ("Three",))
        self.assertEqual(
            narrowed.options[0].supporting_plans,
            (("One", "Two", "Three", "Four"),),
        )
        self.assertEqual(
            narrowed.options[0].input_artifacts,
            (("publishable", 2),),
        )

    def test_boundary_artifact_can_be_used_directly_or_refined_first(self):
        draft = Artifact("draft")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("Publish", inputs=[draft], outputs=[target]),
            Tool("Refine", inputs=[draft], outputs=[draft]),
            starting=("draft",),
        )

        plans = {
            tuple(plan.tool_names): plan
            for plan in workflow.discover_plans()
        }

        self.assertEqual(
            set(plans),
            {("Publish",), ("Publish", "Refine")},
        )
        self.assertEqual(
            plans[("Publish",)].producers_for_input("Publish", "draft"),
            (),
        )
        self.assertEqual(
            plans[("Publish", "Refine")].producers_for_input(
                "Publish",
                "draft",
            ),
            ("Refine",),
        )

        project = Project(workflow)
        advisor = Advisor(project)
        initial = advisor.advise()
        publish = next(
            option
            for option in initial.options
            if option.tool_name == "Publish"
        )
        self.assertEqual(publish.supporting_plans, (("Publish",),))

        project.record_tool_success("Refine")
        gate = advisor.advise()
        self.assertEqual(
            tuple(
                (option.tool_name, option.cycle_action)
                for option in gate.options
            ),
            (("Refine", "REPEAT"), ("Publish", "EXIT")),
        )


class TestFrontierCompatiblePlanSupport(unittest.TestCase):
    @staticmethod
    def make_project() -> tuple[Project, Advisor]:
        start = Artifact("start")
        shared_input = Artifact("shared input")
        common = Artifact("common")
        seven_output = Artifact("seven output")
        route_c_key = Artifact("route C key")
        shared_output = Artifact("shared output")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("One", inputs=[start], outputs=[common]),
            Tool("Two", inputs=[shared_input], outputs=[shared_output]),
            Tool(
                "Finish A",
                inputs=[common, shared_output],
                outputs=[target],
            ),
            Tool(
                "Finish B",
                inputs=[common, shared_output],
                outputs=[target],
            ),
            Tool("Seven", inputs=[common], outputs=[seven_output]),
            Tool(
                "Three",
                inputs=[seven_output],
                outputs=[shared_input, route_c_key],
            ),
            Tool(
                "Finish C",
                inputs=[shared_output, route_c_key],
                outputs=[target],
            ),
            # ``shared input`` is an external requirement on routes A/B, not
            # a workflow-wide start. Route C deliberately produces a fresh
            # version before ``Two``.
            starting=("start",),
        )
        project = Project(workflow)

        def resolved_plan(
            tool_names: tuple[str, ...],
            bindings: dict[tuple[str, str], tuple[str, ...]],
            target_producer: str,
        ) -> Plan:
            plan = Plan()
            for tool in workflow.tools:
                if tool.name in tool_names:
                    plan.add_tool(tool)
            plan.starting_artifacts = ["start"]
            plan.target_artifacts = ["target"]
            plan.set_input_producers(bindings)
            plan.set_target_producers({
                "target": (target_producer,),
            })
            return plan

        plans = (
            resolved_plan(
                ("One", "Two", "Finish A"),
                {
                    ("One", "start"): (),
                    ("Two", "shared input"): (),
                    ("Finish A", "common"): ("One",),
                    ("Finish A", "shared output"): ("Two",),
                },
                "Finish A",
            ),
            resolved_plan(
                ("One", "Two", "Finish B"),
                {
                    ("One", "start"): (),
                    ("Two", "shared input"): (),
                    ("Finish B", "common"): ("One",),
                    ("Finish B", "shared output"): ("Two",),
                },
                "Finish B",
            ),
            resolved_plan(
                ("One", "Two", "Seven", "Three", "Finish C"),
                {
                    ("One", "start"): (),
                    ("Two", "shared input"): ("Three",),
                    ("Seven", "common"): ("One",),
                    ("Three", "seven output"): ("Seven",),
                    ("Finish C", "shared output"): ("Two",),
                    ("Finish C", "route C key"): ("Three",),
                },
                "Finish C",
            ),
        )
        # The workflow graph alone cannot express route-specific ordering
        # when the same tool consumes an artifact that may also be supplied
        # externally. Feed the Advisor the exact producer-resolved routes so
        # this regression isolates its route-position behavior.
        with patch.object(
            workflow,
            "discover_plans",
            return_value=list(plans),
        ):
            advisor = Advisor(project, max_options=3)
        return project, advisor

    def test_selecting_a_shared_tool_parks_routes_where_it_is_still_later(
        self,
    ):
        project, advisor = self.make_project()
        route_c = ("One", "Two", "Seven", "Three", "Finish C")
        self.assertIn(
            route_c,
            {tuple(plan.tool_names) for plan in advisor.plans},
        )
        project.record_tool_success("One")

        command = advisor.advise()
        self.assertEqual(set(option_names(command)), {"Two", "Seven"})
        shared = next(
            option
            for option in command.options
            if option.tool_name == "Two"
        )
        self.assertEqual(shared.missing_artifacts, ("shared input",))
        self.assertEqual(
            set(shared.supporting_plans),
            {
                ("One", "Two", "Finish A"),
                ("One", "Two", "Finish B"),
            },
        )

        project.record_tool_success("Two")
        narrowed = advisor.advise()

        self.assertEqual(option_names(narrowed), ("Finish A", "Finish B"))
        self.assertNotIn("Seven", option_names(narrowed))
        self.assertNotIn("Finish C", option_names(narrowed))

    def test_parked_later_route_returns_only_after_active_routes_exhaust(
        self,
    ):
        project, advisor = self.make_project()
        project.record_tool_success("One")
        advisor.advise()
        project.record_tool_success("Two")
        advisor.advise()

        project.record_tool_failure("Finish A")
        advisor.advise()
        project.record_tool_failure("Finish A")
        advisor.advise()
        project.record_tool_failure("Finish B")
        advisor.advise()
        project.record_tool_failure("Finish B")

        restored = advisor.advise()

        self.assertEqual(option_names(restored), ("Seven",))
        self.assertEqual(restored.options[0].action, "ALTERNATIVE")


class TestProducerRouteIdentity(unittest.TestCase):
    @staticmethod
    def make_workflow() -> Workflow:
        start = Artifact("start")
        shared = Artifact("shared")
        a_key = Artifact("A key")
        b_key = Artifact("B key")
        consumed = Artifact("consumed")
        target = Artifact("target")
        return make_workflow(
            Tool("A", inputs=[start], outputs=[shared, a_key]),
            Tool("B", inputs=[start], outputs=[shared, b_key]),
            Tool("Consume", inputs=[shared], outputs=[consumed]),
            Tool(
                "Finish",
                inputs=[a_key, b_key, consumed],
                outputs=[target],
            ),
            starting=("start",),
        )

    def test_same_tool_set_retains_each_distinct_producer_binding(self):
        plans = self.make_workflow().discover_plans()

        self.assertEqual(len(plans), 2)
        self.assertEqual(
            {tuple(plan.tool_names) for plan in plans},
            {("A", "B", "Consume", "Finish")},
        )
        self.assertEqual(
            {
                plan.producers_for_input("Consume", "shared")
                for plan in plans
            },
            {("A",), ("B",)},
        )

    def test_each_producer_choice_exposes_its_valid_frontier(self):
        for completed, remaining in (("A", "B"), ("B", "A")):
            with self.subTest(completed=completed):
                project = Project(self.make_workflow())
                advisor = Advisor(project)
                self.assertEqual(
                    set(option_names(advisor.advise())),
                    {"A", "B"},
                )
                project.record_tool_success(completed)

                self.assertEqual(
                    set(option_names(advisor.advise())),
                    {remaining, "Consume"},
                )

    def test_history_replays_the_exact_binding_not_only_tool_names(self):
        project = Project(self.make_workflow())
        advisor = Advisor(project)
        advisor.advise()

        project.record_tool_success("A")
        after_a = advisor.advise()
        consume = next(
            option
            for option in after_a.options
            if option.tool_name == "Consume"
        )
        self.assertEqual(len(consume.supporting_route_keys), 1)

        project.record_tool_success("Consume")
        after_consume = advisor.advise()

        self.assertEqual(option_names(after_consume), ("B",))
        self.assertEqual(len(after_consume.options[0].supporting_route_keys), 1)

    def test_newer_producer_version_invalidates_the_older_binding(self):
        project = Project(self.make_workflow())
        advisor = Advisor(project)
        project.record_tool_success("A")
        project.record_tool_success("B")

        command = advisor.advise()
        consume = next(
            option
            for option in command.options
            if option.tool_name == "Consume"
        )

        self.assertEqual(consume.input_artifacts, (("shared", 2),))
        self.assertEqual(len(consume.supporting_route_keys), 1)
        self.assertEqual(
            {
                (consumer, artifact): producers
                for consumer, artifact, producers
                in consume.supporting_route_keys[0][3]
            }[("Consume", "shared")],
            ("B",),
        )

    def test_external_overwrite_does_not_satisfy_an_internal_binding(self):
        project = Project(self.make_workflow())
        advisor = Advisor(project)
        project.record_tool_success("A")
        project.record_artifact_available("shared")

        self.assertNotIn("Consume", option_names(advisor.advise()))


class TestRouteAwareProducerValidation(unittest.TestCase):
    def test_boundary_consumer_stays_independent_of_selected_producer(self):
        start = Artifact("start")
        shared = Artifact("shared")
        required = Artifact("required")
        consumed = Artifact("consumed")
        target = Artifact("target")
        workflow = make_workflow(
            Tool(
                "Produce",
                inputs=[start],
                outputs=[shared, required],
            ),
            Tool("Consume", inputs=[shared], outputs=[consumed]),
            Tool(
                "Finish",
                inputs=[consumed, required],
                outputs=[target],
            ),
            starting=("start", "shared"),
        )

        plans = workflow.discover_plans()

        self.assertIn(
            (),
            {
                plan.producers_for_input("Consume", "shared")
                for plan in plans
            },
        )
        command = Advisor(Project(workflow)).advise()
        self.assertEqual(
            set(option_names(command)),
            {"Produce", "Consume"},
        )

    def test_validator_does_not_use_an_unchosen_producer_edge(self):
        start = Artifact("start")
        external = Artifact("external")
        shared = Artifact("shared")
        second_input = Artifact("second input")
        first_target = Artifact("first target")
        second_target = Artifact("second target")
        workflow = make_workflow(
            Tool(
                "Reachable producer",
                inputs=[start],
                outputs=[shared, second_input],
            ),
            Tool(
                "External producer",
                inputs=[external],
                outputs=[shared],
            ),
            Tool(
                "First target",
                inputs=[shared],
                outputs=[first_target],
            ),
            Tool(
                "Second target",
                inputs=[second_input],
                outputs=[second_target],
            ),
            starting=("start",),
            target=("first target", "second target"),
        )

        plans = workflow.discover_plans()

        self.assertEqual(
            [tuple(plan.tool_names) for plan in plans],
            [
                (
                    "Reachable producer",
                    "First target",
                    "Second target",
                ),
            ],
        )
        self.assertEqual(
            plans[0].producers_for_input("First target", "shared"),
            ("Reachable producer",),
        )


class TestContinuationCycleBoundaries(unittest.TestCase):
    def test_available_non_anchor_seeds_a_deviation_cycle(self):
        start = Artifact("start")
        prepared = Artifact("prepared")
        cycle_input = Artifact("cycle input")
        cycle_output = Artifact("cycle output")
        deviation_anchor = Artifact("deviation anchor")
        target = Artifact("target")
        workflow = make_workflow(
            Tool(
                "Prepare",
                inputs=[start],
                outputs=[prepared, cycle_input],
            ),
            Tool("Preferred", inputs=[prepared], outputs=[target]),
            starting=("start",),
        )
        network = workflow.to_tool_network()
        network.add_tool(
            Tool(
                "Deviate",
                inputs=[prepared],
                outputs=[deviation_anchor],
            )
        )
        # Put the other cycle seed first so insertion-order fallback would
        # ask for it unless the route remembers the available ``cycle input``.
        network.add_tool(
            Tool(
                "Cycle back",
                inputs=[cycle_output],
                outputs=[cycle_input],
            )
        )
        network.add_tool(
            Tool(
                "Cycle forward",
                inputs=[cycle_input],
                outputs=[cycle_output],
            )
        )
        network.add_tool(
            Tool(
                "Exit",
                inputs=[cycle_output, deviation_anchor],
                outputs=[target],
            )
        )
        project = Project(workflow, tool_network=network)
        advisor = Advisor(project, policy=OPPORTUNISTIC)

        advisor.advise()
        project.record_tool_success("Prepare")
        advisor.advise()
        project.record_tool_success("Deviate")

        command = advisor.advise()
        forward = next(
            option
            for option in command.options
            if option.tool_name == "Cycle forward"
        )

        self.assertEqual(forward.missing_artifacts, ())
        self.assertEqual(forward.transition, "CONTINUE_CURRENT")
        self.assertEqual(
            tuple(
                route_key[1]
                for route_key in forward.supporting_route_keys
            ),
            (("cycle input", "deviation anchor"),),
        )


class TestExactRouteHistoryFallback(unittest.TestCase):
    def test_matching_legacy_signature_precedes_other_exact_route_keys(self):
        start = Artifact("start")
        a_ready = Artifact("A ready")
        b_ready = Artifact("B ready")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("A", inputs=[start], outputs=[a_ready]),
            Tool("Finish A", inputs=[a_ready], outputs=[target]),
            Tool("B", inputs=[start], outputs=[b_ready]),
            Tool("Finish B", inputs=[b_ready], outputs=[target]),
            starting=("start",),
        )
        project = Project(workflow)
        advisor = Advisor(project)
        plans = {
            tuple(plan.tool_names): plan
            for plan in advisor.plans
        }
        a_key = plans[("A", "Finish A")].route_key
        stale_a_key = (
            a_key[0],
            ("stale start",),
            a_key[2],
            a_key[3],
            a_key[4],
        )

        advisor.advice_history.record(
            event_position=0,
            configuration=advisor._configuration,
            options=(
                AdvisedOption(
                    "A",
                    supporting_plan_signatures=(("A", "Finish A"),),
                    supporting_route_keys=(stale_a_key,),
                ),
                AdvisedOption(
                    "B",
                    supporting_plan_signatures=(("B", "Finish B"),),
                    supporting_route_keys=(
                        plans[("B", "Finish B")].route_key,
                    ),
                ),
            ),
        )
        project.record_tool_success("A")

        command = advisor.advise()

        self.assertIsNone(command.deviation)
        self.assertEqual(option_names(command), ("Finish A",))


class TestCycleDecisionPolicy(unittest.TestCase):
    @staticmethod
    def make_project_at_cycle_decision() -> Project:
        start = Artifact("start")
        draft = Artifact("draft")
        review = Artifact("review")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("Setup", inputs=[start], outputs=[draft]),
            Tool("Review", inputs=[draft], outputs=[review]),
            # Exit is deliberately inserted before repeat. Cycle semantics,
            # rather than insertion order, must decide their presentation.
            Tool("Publish", inputs=[review], outputs=[target]),
            Tool("Revise", inputs=[review], outputs=[draft]),
            starting=("start",),
        )
        project = Project(workflow)
        project.record_tool_success("Setup")
        project.record_tool_success("Review")
        return project

    def test_repeat_precedes_exit_independent_of_insertion_order(self):
        project = self.make_project_at_cycle_decision()

        command = Advisor(project).advise()

        self.assertEqual(option_names(command), ("Revise", "Publish"))
        self.assertEqual(
            tuple(option.cycle_action for option in command.options),
            ("REPEAT", "EXIT"),
        )

    def test_exit_remains_visible_when_max_options_is_one(self):
        project = self.make_project_at_cycle_decision()
        advisor = Advisor(project, max_options=1)

        command = advisor.advise()

        self.assertEqual(option_names(command), ("Revise", "Publish"))
        self.assertFalse(command.options_truncated)

    def test_cycle_gate_is_protected_inside_lookahead(self):
        start = Artifact("start")
        draft = Artifact("draft")
        review = Artifact("review")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("Setup", inputs=[start], outputs=[draft]),
            Tool("Review", inputs=[draft], outputs=[review]),
            Tool("Publish", inputs=[review], outputs=[target]),
            Tool("Revise", inputs=[review], outputs=[draft]),
            starting=("start",),
        )

        command = Advisor(
            Project(workflow),
            lookahead_depth=3,
            max_options=1,
        ).advise()
        review_preview = command.options[0].continuations[0]

        self.assertEqual(
            tuple(
                option.tool_name
                for option in review_preview.continuations
            ),
            ("Revise", "Publish"),
        )

    def test_exit_preparation_survives_cap_and_interleaving(self):
        start = Artifact("start")
        draft = Artifact("draft")
        review = Artifact("review")
        license_artifact = Artifact("license")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("Setup", inputs=[start], outputs=[draft]),
            Tool("Review", inputs=[draft], outputs=[review]),
            Tool(
                "Publish",
                inputs=[review, license_artifact],
                outputs=[target],
            ),
            Tool("Revise", inputs=[review], outputs=[draft]),
            Tool(
                "Get license",
                inputs=[start],
                outputs=[license_artifact],
            ),
            starting=("start",),
        )
        project = Project(workflow)
        advisor = Advisor(project, max_options=1)
        project.record_tool_success("Setup")
        project.record_tool_success("Review")

        preparation_gate = advisor.advise()
        self.assertEqual(
            tuple(
                (option.tool_name, option.cycle_action)
                for option in preparation_gate.options
            ),
            (
                ("Revise", "REPEAT"),
                ("Get license", "EXIT_PREPARATION"),
            ),
        )

        project.record_tool_success("Get license")
        exit_gate = advisor.advise()
        self.assertEqual(
            tuple(
                (option.tool_name, option.cycle_action)
                for option in exit_gate.options
            ),
            (("Revise", "REPEAT"), ("Publish", "EXIT")),
        )

    def test_repeat_returns_to_gate_and_exit_commits_downstream(self):
        project = self.make_project_at_cycle_decision()
        advisor = Advisor(project)

        project.record_tool_success("Revise")
        self.assertEqual(option_names(advisor.advise()), ("Review",))
        project.record_tool_success("Review")
        repeated_gate = advisor.advise()
        self.assertEqual(option_names(repeated_gate), ("Revise", "Publish"))

        project.record_tool_success("Publish")
        self.assertEqual(advisor.advise().status, "COMPLETE")

    def test_exit_retry_precedes_repeat_then_fresh_visit_resets_policy(
        self,
    ):
        project = self.make_project_at_cycle_decision()
        advisor = Advisor(project, max_options=1)
        advisor.advise()

        project.record_tool_failure("Publish")
        recovering = advisor.advise()

        self.assertEqual(
            tuple(
                (option.tool_name, option.action)
                for option in recovering.options
            ),
            (("Publish", "RETRY"), ("Revise", "ALTERNATIVE")),
        )
        self.assertEqual(
            tuple(option.cycle_action for option in recovering.options),
            ("EXIT", "REPEAT"),
        )

        project.record_tool_success("Revise")
        review = advisor.advise().options[0]
        self.assertEqual(review.input_artifacts, (("draft", 2),))
        project.record_tool_success("Review")

        fresh_gate = advisor.advise()
        self.assertEqual(option_names(fresh_gate), ("Revise", "Publish"))
        self.assertEqual(
            tuple(option.action for option in fresh_gate.options),
            ("RUN", "RUN"),
        )
        self.assertEqual(
            tuple(option.input_artifacts for option in fresh_gate.options),
            ((("review", 2),), (("review", 2),)),
        )

    def test_target_acceptance_is_the_visible_exit_from_a_target_cycle(self):
        start = Artifact("start")
        draft = Artifact("draft")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("Write", inputs=[start], outputs=[draft]),
            Tool(
                "Evaluate",
                inputs=[draft],
                outputs=[start, target],
            ),
            starting=("start",),
        )
        project = Project(workflow)
        advisor = Advisor(project, max_options=1)
        project.record_tool_success("Write")
        project.record_tool_success("Evaluate")

        command = advisor.advise()

        self.assertTrue(command.target_acceptance_required)
        self.assertEqual(option_names(command), ("Write",))
        self.assertEqual(command.options[0].cycle_action, "REPEAT")
        project.record_target_acceptance()
        self.assertEqual(advisor.advise().status, "COMPLETE")


class TestCycleGatePairingRegressions(unittest.TestCase):
    def test_max_one_never_pairs_repeat_and_exit_from_different_cycles(self):
        start = Artifact("start")
        draft_one = Artifact("draft one")
        review_one = Artifact("review one")
        accepted_one = Artifact("accepted one")
        draft_two = Artifact("draft two")
        review_two = Artifact("review two")
        accepted_two = Artifact("accepted two")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("Setup one", inputs=[start], outputs=[draft_one]),
            Tool("Review one", inputs=[draft_one], outputs=[review_one]),
            Tool(
                "Repeat one",
                inputs=[review_one],
                outputs=[draft_one],
            ),
            Tool("Setup two", inputs=[start], outputs=[draft_two]),
            Tool("Review two", inputs=[draft_two], outputs=[review_two]),
            # The cross-gate insertion order would expose Repeat one with
            # Exit two if the breadth limiter paired roles globally.
            Tool("Exit two", inputs=[review_two], outputs=[accepted_two]),
            Tool(
                "Repeat two",
                inputs=[review_two],
                outputs=[draft_two],
            ),
            Tool("Exit one", inputs=[review_one], outputs=[accepted_one]),
            Tool(
                "Finish",
                inputs=[accepted_one, accepted_two],
                outputs=[target],
            ),
            starting=("start",),
        )
        project = Project(workflow)
        advisor = Advisor(project, max_options=1)
        for tool_name in (
            "Setup one",
            "Review one",
            "Setup two",
            "Review two",
        ):
            project.record_tool_success(tool_name)

        command = advisor.advise()

        self.assertEqual(
            tuple(option.cycle_action for option in command.options),
            ("REPEAT", "EXIT"),
        )
        self.assertIn(
            frozenset(option_names(command)),
            {
                frozenset(("Repeat one", "Exit one")),
                frozenset(("Repeat two", "Exit two")),
            },
        )
        self.assertTrue(command.options_truncated)

    def test_repeat_with_missing_external_input_still_precedes_ready_exit(
        self,
    ):
        start = Artifact("start")
        draft = Artifact("draft")
        review = Artifact("review")
        guidance = Artifact("guidance")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("Setup", inputs=[start], outputs=[draft]),
            Tool("Review", inputs=[draft], outputs=[review]),
            Tool("Publish", inputs=[review], outputs=[target]),
            Tool(
                "Revise",
                inputs=[review, guidance],
                outputs=[draft],
            ),
            starting=("start",),
        )
        project = Project(workflow)
        advisor = Advisor(project, max_options=1)
        project.record_tool_success("Setup")
        project.record_tool_success("Review")

        command = advisor.advise()

        self.assertEqual(
            tuple(
                (
                    option.tool_name,
                    option.cycle_action,
                    option.missing_artifacts,
                )
                for option in command.options
            ),
            (
                ("Revise", "REPEAT", ("guidance",)),
                ("Publish", "EXIT", ()),
            ),
        )
        self.assertFalse(command.options_truncated)


if __name__ == "__main__":
    unittest.main()
