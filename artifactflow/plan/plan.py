"""One target-reaching plan selected from a workflow."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING

from artifactflow.network.network import Network

if TYPE_CHECKING:
    from artifactflow.workflow.workflow import Workflow


@dataclass(frozen=True, slots=True)
class PlanRequirements:
    """External inputs and one chosen bootstrap set for one plan."""

    external_artifacts: frozenset[str]
    bootstrap_artifacts: frozenset[str]

    @property
    def initial_artifacts(self) -> frozenset[str]:
        """Return everything that must be available to start the plan."""
        return self.external_artifacts | self.bootstrap_artifacts

    @property
    def is_satisfied(self) -> bool:
        """Return whether this requirement set is empty."""
        return not self.initial_artifacts

    def missing(
        self,
        available_artifacts: Iterable[str],
    ) -> PlanRequirements:
        """Return requirements not present in an available artifact set."""
        available = _artifact_names(available_artifacts)
        return PlanRequirements(
            external_artifacts=self.external_artifacts - available,
            bootstrap_artifacts=self.bootstrap_artifacts - available,
        )


class Plan(Network):
    """A target-reaching subset of a workflow.

    A plan contains the tools for one possible route through a workflow.
    Tools that form a cycle are kept together, so a plan is a subnetwork
    rather than a finite sequence of tool calls.
    """

    def __init__(self) -> None:
        super().__init__()
        self.starting_artifacts: list[str] | None = None
        self.target_artifacts: list[str] | None = None

    def input_requirements(self) -> PlanRequirements:
        """Return the plan's structural external and bootstrap inputs.

        External artifacts have no producer in this plan. Bootstrap artifacts
        do have a producer, but an initial version is needed to enter a cycle.
        Declared internal starting artifacts are honored. If the plan needs
        further seeds, the smallest added set is selected; artifact insertion
        order resolves equally small alternatives deterministically.
        """
        if self.starting_artifacts is None:
            raise ValueError(
                "starting_artifacts must be defined before calculating "
                "plan requirements."
            )

        starting = set(self.starting_artifacts)
        unknown = starting - set(self.artifact_names)
        if unknown:
            raise ValueError(f"Unknown artifacts: {sorted(unknown)}")

        consumed = {
            artifact.name
            for tool in self.tools
            for artifact in tool.inputs
        }
        produced = {
            artifact.name
            for tool in self.tools
            for artifact in tool.outputs
        }
        external = consumed - produced
        bootstrap = starting & consumed & produced

        initial = starting | external
        if not self._can_run_once(initial):
            candidates = [
                artifact_name
                for artifact_name in self.artifact_names
                if artifact_name in consumed & produced
                and artifact_name not in initial
            ]
            for number_of_seeds in range(1, len(candidates) + 1):
                selected = next(
                    (
                        set(seeds)
                        for seeds in combinations(
                            candidates,
                            number_of_seeds,
                        )
                        if self._can_run_once(initial | set(seeds))
                    ),
                    None,
                )
                if selected is not None:
                    bootstrap.update(selected)
                    break
            else:
                raise ValueError(
                    "The plan cannot be initialized from its declared "
                    "starting and external artifacts."
                )

        return PlanRequirements(
            external_artifacts=frozenset(external),
            bootstrap_artifacts=frozenset(bootstrap),
        )

    def missing_input_requirements(
        self,
        available_artifacts: Iterable[str],
    ) -> PlanRequirements:
        """Return the plan requirements not currently available."""
        return self.input_requirements().missing(available_artifacts)

    def _can_run_once(self, initial_artifacts: set[str]) -> bool:
        """Return whether every plan tool can run once from these artifacts."""
        available = set(initial_artifacts)
        remaining = list(self.tools)

        while remaining:
            ready_tools = [
                tool
                for tool in remaining
                if {
                    artifact.name
                    for artifact in tool.inputs
                } <= available
            ]
            if not ready_tools:
                return False

            for tool in ready_tools:
                available.update(
                    artifact.name
                    for artifact in tool.outputs
                )
                remaining.remove(tool)

        return True

    @classmethod
    def from_workflow(cls, workflow: Workflow) -> Plan:
        """Create a plan containing the same tools and boundaries."""
        from artifactflow.workflow.workflow import Workflow

        if not isinstance(workflow, Workflow):
            raise TypeError("workflow must be a Workflow.")

        plan = cls()
        for tool in workflow.tools:
            plan.add_tool(tool)
        plan.starting_artifacts = deepcopy(workflow.starting_artifacts)
        plan.target_artifacts = deepcopy(workflow.target_artifacts)
        return plan


def _artifact_names(artifacts: Iterable[str]) -> frozenset[str]:
    names = (artifacts,) if isinstance(artifacts, str) else tuple(artifacts)
    if not all(isinstance(name, str) for name in names):
        raise TypeError("available_artifacts must contain artifact names.")
    return frozenset(names)
