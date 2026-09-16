from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import networkx as nx
import numpy as np
from numpy.typing import NDArray

from artifactflow.tool import Tool
from artifactflow.network.graphics import Graphics


@dataclass(frozen=True, slots=True)
class ToolDependencyMatrix:
    """
    A tool DSM together with its shared row and column labels.
    """

    matrix: NDArray[np.int64]
    tool_names: tuple[str, ...]

    @property
    def tool_indices(self) -> dict[str, int]:
        """
        Return each tool's row and column index in the matrix.
        """
        return {
            tool_name: index
            for index, tool_name in enumerate(self.tool_names)
        }


@dataclass(frozen=True, slots=True)
class _ProducerRoute:
    """
    One target derivation with route-specific producer selections.
    """

    tool_names: frozenset[str]
    boundary_artifacts: tuple[str, ...]
    input_producers: tuple[
        tuple[str, str, tuple[str, ...]],
        ...,
    ]
    target_producers: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def key(self) -> tuple[object, ...]:
        """
        Return an exact identity for this resolved causal route.
        """
        return (
            self.tool_names,
            self.boundary_artifacts,
            self.input_producers,
            self.target_producers,
        )


class Network(
    Graphics,
):
    """
    Super class for Workflow and ToolNetwork classes.
    """

    def __init__(
        self,
    ):
        self.tools = []
        self.G = nx.DiGraph()

    @property
    def tool_names(self) -> list[str]:
        return [tool.name for tool in self.tools]

    @property
    def artifact_names(self) -> list[str]:
        """
        Return artifact names independently of display-graph node keys.
        """
        return list(dict.fromkeys(
            artifact.name
            for tool in self.tools
            for artifact in (*tool.inputs, *tool.outputs)
        ))

    def contains_tool(self, tool_name: str) -> bool:
        """
        Return whether this network contains a named tool.
        """
        if not isinstance(tool_name, str):
            raise TypeError("tool_name must be a string.")
        return tool_name in self.tool_names

    def to_tool_dependency_graph(self) -> nx.DiGraph:
        """
        Return a tool-only projection of the artifact dependency graph.

        Each edge points from an artifact producer to an artifact consumer.
        When several artifacts connect the same two tools, their names are
        stored together in the edge's ``artifacts`` attribute.
        """
        tool_graph = nx.DiGraph()
        tool_graph.add_nodes_from(
            (
                tool.name,
                {"type": "tool"},
            )
            for tool in self.tools
        )

        for artifact_name in self.artifact_names:
            producer_names = [
                tool.name
                for tool in self.tools
                if any(
                    artifact.name == artifact_name
                    for artifact in tool.outputs
                )
            ]
            consumer_names = [
                tool.name
                for tool in self.tools
                if any(
                    artifact.name == artifact_name
                    for artifact in tool.inputs
                )
            ]

            for producer_name in producer_names:
                for consumer_name in consumer_names:
                    if tool_graph.has_edge(producer_name, consumer_name):
                        tool_graph[producer_name][consumer_name][
                            "artifacts"
                        ].append(artifact_name)
                    else:
                        tool_graph.add_edge(
                            producer_name,
                            consumer_name,
                            artifacts=[artifact_name],
                        )

        return tool_graph

    def _discover_producer_routes(
        self,
        *,
        boundary_artifacts: Iterable[str],
        target_artifacts: Iterable[str],
        validator: Callable[[_ProducerRoute], bool],
    ) -> tuple[_ProducerRoute, ...]:
        """
        Discover target routes by choosing producers, not tool supersets.

        Each target and each internally supplied tool input chooses one
        producer. This retains a longer refinement route when it selects a
        different producer for a downstream artifact, while avoiding the
        arbitrary union of otherwise independent target-reaching branches.
        Strongly connected tool components remain atomic so cycles are
        structural rather than unrolled into infinitely many routes.
        """
        boundary_order = tuple(dict.fromkeys(boundary_artifacts))
        boundary = frozenset(boundary_order)
        targets = tuple(dict.fromkeys(target_artifacts))
        tool_graph = self.to_tool_dependency_graph()
        tool_positions = {
            tool.name: position
            for position, tool in enumerate(self.tools)
        }

        components = [
            frozenset(component)
            for component in nx.strongly_connected_components(tool_graph)
        ]
        components.sort(
            key=lambda component: min(
                tool_positions[name]
                for name in component
            )
        )
        unit_by_tool = {
            tool_name: unit_index
            for unit_index, component in enumerate(components)
            for tool_name in component
        }
        cyclic_units = {
            unit_index
            for unit_index, component in enumerate(components)
            if len(component) > 1
            or any(tool_graph.has_edge(name, name) for name in component)
        }
        unit_inputs = {
            unit_index: tuple(
                (tool.name, artifact.name, False)
                for tool in self.tools
                if tool.name in component
                for artifact in tool.inputs
            )
            for unit_index, component in enumerate(components)
        }
        producers_by_artifact = {
            artifact_name: tuple(
                tool.name
                for tool in self.tools
                if any(
                    output.name == artifact_name
                    for output in tool.outputs
                )
            )
            for artifact_name in self.artifact_names
        }

        # An obligation is (consumer tool or None for a target, artifact,
        # force fresh production). Choices retain the causal witness needed
        # to distinguish direct and refinement Plans with overlapping tools.
        initial_pending = tuple(
            (None, target_name, True)
            for target_name in targets
        )
        stack: list[
            tuple[
                frozenset[int],
                tuple[tuple[str | None, str, bool], ...],
                tuple[tuple[str | None, str, str | None], ...],
            ]
        ] = [(frozenset(), initial_pending, ())]
        completed: dict[tuple[object, ...], _ProducerRoute] = {}
        visited: set[tuple[object, ...]] = set()

        while stack:
            selected_units, pending, choices = stack.pop()
            state_key = (selected_units, pending, choices)
            if state_key in visited:
                continue
            visited.add(state_key)

            if not pending:
                selected_names = frozenset(
                    tool_name
                    for unit_index in selected_units
                    for tool_name in components[unit_index]
                )
                if not selected_names:
                    continue

                choice_map = {
                    (consumer_name, artifact_name): producer_name
                    for consumer_name, artifact_name, producer_name in choices
                }
                bindings: list[
                    tuple[str, str, tuple[str, ...]]
                ] = []
                for tool in self.tools:
                    if tool.name not in selected_names:
                        continue
                    consumer_unit = unit_by_tool[tool.name]
                    for artifact in tool.inputs:
                        selected_producers = tuple(
                            producer_name
                            for producer_name in producers_by_artifact.get(
                                artifact.name,
                                (),
                            )
                            if producer_name in selected_names
                        )
                        chosen = choice_map.get((tool.name, artifact.name))
                        bound: list[str] = []

                        # Preserve every selected feedback edge inside one
                        # cyclic unit. A separately selected producer remains
                        # the entry edge for the first visit to that cycle.
                        if consumer_unit in cyclic_units:
                            bound.extend(
                                producer_name
                                for producer_name in selected_producers
                                if unit_by_tool[producer_name] == consumer_unit
                            )
                        if chosen is not None and chosen in selected_names:
                            bound.append(chosen)

                        bindings.append((
                            tool.name,
                            artifact.name,
                            tuple(dict.fromkeys(bound)),
                        ))

                target_bindings = tuple(
                    (target_name, (producer_name,))
                    for target_name in targets
                    if (
                        producer_name := choice_map.get((None, target_name))
                    ) is not None
                )
                chosen_boundaries = tuple(
                    artifact_name
                    for artifact_name in boundary_order
                    if any(
                        chosen_artifact == artifact_name
                        and producer_name is None
                        for _consumer_name, chosen_artifact, producer_name
                        in choices
                    )
                )
                route = _ProducerRoute(
                    tool_names=selected_names,
                    boundary_artifacts=chosen_boundaries,
                    input_producers=tuple(bindings),
                    target_producers=target_bindings,
                )
                if validator(route):
                    completed.setdefault(route.key, route)
                continue

            consumer_name, artifact_name, force_production = pending[0]
            remaining = pending[1:]
            choice_key = (consumer_name, artifact_name)

            producer_names = producers_by_artifact.get(artifact_name, ())
            candidate_producers = producer_names
            if not force_production and artifact_name in boundary:
                # Available inputs normally terminate a continuation. The
                # deliberate exception is a feedback producer: selecting it
                # represents an optimization/refinement cycle rather than an
                # unnecessary recreation of an already usable prerequisite.
                candidate_producers = tuple(
                    producer_name
                    for producer_name in producer_names
                    if unit_by_tool[producer_name] in cyclic_units
                )
            next_states: list[
                tuple[
                    frozenset[int],
                    tuple[tuple[str | None, str, bool], ...],
                    tuple[tuple[str | None, str, str | None], ...],
                ]
            ] = []

            # Consuming an available boundary version and producing a fresh
            # version are separate causal routes. Explore both; selecting an
            # already selected SCC does not enqueue it again, so feedback
            # routes remain finite.
            if not force_production and (
                artifact_name in boundary or not producer_names
            ):
                next_states.append((
                    selected_units,
                    remaining,
                    (*choices, (*choice_key, None)),
                ))

            for producer_name in candidate_producers:
                unit_index = unit_by_tool[producer_name]
                newly_selected = unit_index not in selected_units
                next_units = selected_units | {unit_index}
                next_pending = remaining
                if newly_selected:
                    next_pending = (*unit_inputs[unit_index], *remaining)
                next_states.append((
                    frozenset(next_units),
                    next_pending,
                    (*choices, (*choice_key, producer_name)),
                ))

            # Preserve boundary-first, then network insertion order, under
            # the LIFO traversal.
            stack.extend(reversed(next_states))

        return tuple(sorted(
            completed.values(),
            key=lambda route: (
                tuple(
                    position
                    for position, tool in enumerate(self.tools)
                    if tool.name in route.tool_names
                ),
                route.boundary_artifacts,
                route.input_producers,
                route.target_producers,
            ),
        ))

    def _producer_route_graph(
        self,
        route: _ProducerRoute,
        boundary_artifacts: Iterable[str],
    ) -> nx.DiGraph:
        """
        Return a causal graph containing only the selected route edges.

        Intermediate artifact names are intentionally absent. Reusing one
        shared artifact node would let an unchosen producer fabricate a path
        through a consumer that is actually bound to another producer.
        """
        declared_boundary = frozenset(boundary_artifacts)
        boundary = frozenset(route.boundary_artifacts)
        if not boundary <= declared_boundary:
            raise ValueError(
                "Route boundary artifacts must be declared available."
            )
        graph = nx.DiGraph()
        graph.add_nodes_from(
            ("tool", tool_name)
            for tool_name in route.tool_names
        )

        tool_graph = nx.DiGraph()
        tool_graph.add_nodes_from(route.tool_names)
        for consumer_name, _artifact_name, producer_names in (
            route.input_producers
        ):
            for producer_name in producer_names:
                tool_graph.add_edge(producer_name, consumer_name)
        cyclic_components = tuple(
            frozenset(component)
            for component in nx.strongly_connected_components(tool_graph)
            if len(component) > 1
            or any(tool_graph.has_edge(name, name) for name in component)
        )

        for consumer_name, artifact_name, producer_names in (
            route.input_producers
        ):
            consumer_node = ("tool", consumer_name)
            if not producer_names:
                source_kind = (
                    "boundary"
                    if artifact_name in boundary
                    else "external"
                )
                graph.add_edge(
                    (source_kind, artifact_name),
                    consumer_node,
                )
                continue

            for producer_name in producer_names:
                graph.add_edge(
                    ("tool", producer_name),
                    consumer_node,
                )

            # A declared boundary version can seed the first visit to a
            # feedback component; subsequent visits use its feedback edge.
            if artifact_name in boundary and any(
                consumer_name in component
                and producer_name in component
                for component in cyclic_components
                for producer_name in producer_names
            ):
                graph.add_edge(
                    ("boundary", artifact_name),
                    consumer_node,
                )

        for target_name, producer_names in route.target_producers:
            target_node = ("target", target_name)
            graph.add_node(target_node)
            for producer_name in producer_names:
                graph.add_edge(("tool", producer_name), target_node)

        return graph

    def _typed_dependency_graph(
        self,
        tool_names: frozenset[str] | set[str] | None = None,
    ) -> nx.DiGraph:
        """
        Return a bipartite graph whose typed keys cannot collide.

        ``G`` remains the package's concise public/display graph and uses
        plain names as node keys. Structural analysis uses this private graph
        so a tool and artifact may safely have the same public name.
        """
        selected_names = (
            set(self.tool_names)
            if tool_names is None
            else set(tool_names)
        )
        graph = nx.DiGraph()

        for tool in self.tools:
            if tool.name not in selected_names:
                continue

            tool_node = ("tool", tool.name)
            graph.add_node(tool_node, type="tool", name=tool.name)
            for artifact in tool.inputs:
                artifact_node = ("artifact", artifact.name)
                graph.add_node(
                    artifact_node,
                    type="artifact",
                    name=artifact.name,
                )
                graph.add_edge(artifact_node, tool_node, type="input")
            for artifact in tool.outputs:
                artifact_node = ("artifact", artifact.name)
                graph.add_node(
                    artifact_node,
                    type="artifact",
                    name=artifact.name,
                )
                graph.add_edge(tool_node, artifact_node, type="output")

        return graph

    def to_tool_dependency_matrix(self) -> ToolDependencyMatrix:
        """
        Return the tool design structure matrix (DSM).

        Rows and columns follow ``tool_names`` order. A value at
        ``matrix[producer, consumer]`` is one when the row tool supplies at
        least one artifact to the column tool, and zero otherwise. The
        diagonal is always one. With tools in execution order, feedforward
        dependencies appear above the diagonal and feedback dependencies
        appear below it.
        """
        tool_graph = self.to_tool_dependency_graph()
        tool_names = tuple(self.tool_names)
        tool_indices = {
            tool_name: index
            for index, tool_name in enumerate(tool_names)
        }
        matrix = np.zeros(
            (len(tool_names), len(tool_names)),
            dtype=np.int64,
        )

        for producer_name, consumer_name in tool_graph.edges:
            matrix[
                tool_indices[producer_name],
                tool_indices[consumer_name],
            ] = 1

        np.fill_diagonal(matrix, 1)

        return ToolDependencyMatrix(
            matrix=matrix,
            tool_names=tool_names,
        )

    def producer_conflicts(self) -> dict[str, list[str]]:
        """
        Return artifacts produced by more than one tool.

        Artifact and producer ordering follows their insertion order in the
        network.
        """
        conflicts = {}

        for artifact_name in self.artifact_names:
            producer_names = {
                tool.name
                for tool in self.tools
                if any(
                    artifact.name == artifact_name
                    for artifact in tool.outputs
                )
            }

            if len(producer_names) < 2:
                continue

            conflicts[artifact_name] = [
                tool.name
                for tool in self.tools
                if tool.name in producer_names
            ]

        return conflicts

    def has_producer_conflicts(self) -> bool:
        """
        Return whether any artifact has more than one producer tool.
        """
        return bool(self.producer_conflicts())

    def add_tool(self, tool: Tool):
        if tool.name in self.tool_names:
            raise ValueError(
                f"Tool with name {tool.name} already exists in the network."
            )
        self.tools.append(tool)
        self.G.add_node(tool.name, type='tool')

        for artifact in tool.inputs:
            self.G.add_node(artifact.name, type='artifact')
            self.G.add_edge(artifact.name, tool.name, type='input')

        for artifact in tool.outputs:
            self.G.add_node(artifact.name, type='artifact')
            self.G.add_edge(tool.name, artifact.name, type='output')

    def remove_tool(self, tool_name: str) -> None:
        if tool_name not in self.tool_names:
            raise ValueError(
                f"Tool with name {tool_name} does not exist in the network."
            )

        artifacts = set(self.G.predecessors(tool_name))
        artifacts.update(self.G.successors(tool_name))

        self.tools = [
            tool
            for tool in self.tools
            if tool.name != tool_name
        ]

        # NetworkX automatically removes the tool's edges.
        self.G.remove_node(tool_name)

        # Remove artifacts that are no longer connected to any tool.
        for artifact in artifacts:
            if self.G.degree(artifact) == 0:
                self.G.remove_node(artifact)
        

if __name__ == "__main__":

    from artifactflow.tool.examples import tool_1, tool_2, tool_3, tool_4

    network = Network()
    network.add_tool(tool_1)
    network.add_tool(tool_2)
    network.add_tool(tool_3)
    network.add_tool(tool_4)

    print(network.producer_conflicts())
    dsm = network.to_tool_dependency_matrix()
    print(dsm.matrix, dsm.tool_names)

    network.show()
