from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from artifactflow.network.network import Network
from artifactflow.tool.compatibility.tools_compatibility import tool_readiness
from artifactflow.similarity.qap import QAPStudy

if TYPE_CHECKING:
    from artifactflow.tool_network.tool_network import ToolNetwork


@dataclass(frozen=True, slots=True)
class WorkflowInputRequirements:
    """
    Artifacts needed to initialize and repeatedly run a workflow.
    """

    external_artifacts: frozenset[str]
    bootstrap_artifacts: frozenset[str]
    blocked_tools: frozenset[str]
    unreplenished_bootstrap_artifacts: frozenset[str]

    @property
    def initial_artifacts(self) -> frozenset[str]:
        """
        Return every artifact that must exist before the first run.
        """
        return self.external_artifacts | self.bootstrap_artifacts

    @property
    def is_runnable(self) -> bool:
        """
        Whether one run completes and replenishes its bootstrap inputs.
        """
        return (
            not self.blocked_tools
            and not self.unreplenished_bootstrap_artifacts
        )

    def __str__(self):
        return f'''
            "External Artifacts": {list(self.external_artifacts)},
            "Bootstrap Artifacts": {list(self.bootstrap_artifacts)},
        '''


class Workflow(
    Network,
):

    def __init__(self):
        super().__init__()

        self.starting_artifacts: list[str] | None = None
        self.target_artifacts: list[str] | None = None

    def following_tools(
        self,
        tool_names: str | Iterable[str],
    ) -> tuple[str, ...]:
        """Return tools that consume an output of the given tool or tools."""
        names = (
            (tool_names,)
            if isinstance(tool_names, str)
            else tuple(tool_names)
        )
        unknown = set(names) - set(self.tool_names)
        if unknown:
            raise ValueError(f"Unknown tools: {sorted(unknown)}")

        output_artifacts = {
            artifact.name
            for tool in self.tools
            if tool.name in names
            for artifact in tool.outputs
        }
        return tuple(
            tool.name
            for tool in self.tools
            if any(
                artifact.name in output_artifacts
                for artifact in tool.inputs
            )
        )

    def input_requirements(
        self,
        starting_tools: list[str],
    ) -> WorkflowInputRequirements:
        """
        Analyze persistent external inputs and first-run bootstrap inputs.

        Starting tools are required to execute before any other tools. Their
        internally produced inputs must therefore be supplied for the first
        run. The method then simulates one run to check that all tools can
        execute and that those bootstrap artifacts are produced again.
        """
        if not starting_tools:
            raise ValueError("At least one starting tool is required.")

        starting_tool_names = set(starting_tools)
        available_tool_names = set(self.tool_names)
        unknown_tools = starting_tool_names - available_tool_names

        if unknown_tools:
            raise ValueError(
                f"Unknown starting tools: {sorted(unknown_tools)}"
            )

        external_artifacts = {
            artifact_name
            for artifact_name, data in self.G.nodes(data=True)
            if data["type"] == "artifact"
            and any(
                self.G.nodes[consumer_name]["type"] == "tool"
                for consumer_name in self.G.successors(artifact_name)
            )
            and not any(
                self.G.nodes[producer_name]["type"] == "tool"
                for producer_name in self.G.predecessors(artifact_name)
            )
        }

        bootstrap_artifacts = {
            artifact.name
            for tool in self.tools
            if tool.name in starting_tool_names
            for artifact in tool.inputs
            if any(
                self.G.nodes[producer_name]["type"] == "tool"
                for producer_name in self.G.predecessors(artifact.name)
            )
        }

        available_artifacts = (
            external_artifacts | bootstrap_artifacts
        )
        executed_tool_names = set(starting_tool_names)
        produced_artifacts = {
            artifact.name
            for tool in self.tools
            if tool.name in starting_tool_names
            for artifact in tool.outputs
        }
        available_artifacts.update(produced_artifacts)

        made_progress = True

        while made_progress:
            made_progress = False

            for tool in self.tools:
                if tool.name in executed_tool_names:
                    continue

                input_names = {
                    artifact.name
                    for artifact in tool.inputs
                }

                if not input_names <= available_artifacts:
                    continue

                output_names = {
                    artifact.name
                    for artifact in tool.outputs
                }
                executed_tool_names.add(tool.name)
                produced_artifacts.update(output_names)
                available_artifacts.update(output_names)
                made_progress = True

        blocked_tools = (
            available_tool_names - executed_tool_names
        )
        unreplenished_bootstrap_artifacts = (
            bootstrap_artifacts - produced_artifacts
        )

        return WorkflowInputRequirements(
            external_artifacts=frozenset(external_artifacts),
            bootstrap_artifacts=frozenset(bootstrap_artifacts),
            blocked_tools=frozenset(blocked_tools),
            unreplenished_bootstrap_artifacts=frozenset(
                unreplenished_bootstrap_artifacts
            ),
        )

    def tool_readiness_scores(
        self,
        missing_input_penalty_ratio: float = 1.0,
    ) -> dict[str, float]:
        """
        Return readiness scores for tools with internal producers.
        """
        if missing_input_penalty_ratio < 0:
            raise ValueError(
                "missing_input_penalty_ratio cannot be negative."
            )

        scores = {}

        for candidate_tool in self.tools:
            producer_names = {
                producer_name
                for artifact_name in self.G.predecessors(candidate_tool.name)
                for producer_name in self.G.predecessors(artifact_name)
                if producer_name != candidate_tool.name
                and self.G.nodes[producer_name]["type"] == "tool"
            }

            if not producer_names:
                continue

            previous_tools = [
                tool
                for tool in self.tools
                if tool.name in producer_names
            ]

            scores[candidate_tool.name] = tool_readiness(
                previous_tools=previous_tools,
                candidate_tool=candidate_tool,
                missing_input_penalty_ratio=missing_input_penalty_ratio,
            )

        return scores

    def compatibility_score(
        self,
        missing_input_penalty_ratio: float = 1.0,
    ) -> float:
        """
        Return the mean readiness of tools with internal producers.

        A workflow without tool-to-tool handoffs has no incompatibilities and
        therefore receives a score of 1.0.
        """
        scores = self.tool_readiness_scores(
            missing_input_penalty_ratio=missing_input_penalty_ratio,
        )

        if not scores:
            return 1.0

        return sum(scores.values()) / len(scores)

    def similarity_score(self, other: Workflow) -> float:
        """
        Return the observed typed-node QAP correlation with another workflow.

        The workflows are aligned to the union of their tool and artifact
        nodes. This method does not run a permutation significance test.
        """
        if not isinstance(other, Workflow):
            raise TypeError("other must be a Workflow.")

        study = QAPStudy(
            networks={
                "Workflow A": self.G,
                "Workflow B": other.G,
            },
        )
        return study.correlation("Workflow A", "Workflow B")

    def __add__(
        self,
        other: Workflow,
    ) -> ToolNetwork:
        from artifactflow.tool_network.tool_network import ToolNetwork

        if not isinstance(other, Workflow):
            raise TypeError(
                "other must be a Workflow."
            )
        result = ToolNetwork()

        if self.starting_artifacts is not None and \
        other.starting_artifacts is not None:
            if self.starting_artifacts == other.starting_artifacts:
                result.starting_artifacts = deepcopy(self.starting_artifacts)
        if self.target_artifacts is not None and \
        other.target_artifacts is not None:
            if self.target_artifacts == other.target_artifacts:
                result.target_artifacts = deepcopy(self.target_artifacts)
        
        for tool in self.tools:
            result.add_tool(tool)
        for tool in other.tools:
            if tool.name not in result.tool_names:
                result.add_tool(tool)

        return result


if __name__ == "__main__":

    from artifactflow.tool.examples import tool_1, tool_2, tool_3, tool_4

    workflow = Workflow()
    workflow.add_tool(tool_1)
    workflow.add_tool(tool_2)
    workflow.add_tool(tool_3)
    workflow.add_tool(tool_4)

    print(workflow.compatibility_score())
    print(workflow.input_requirements(starting_tools=["Tool 2"]))

    workflow.show()
