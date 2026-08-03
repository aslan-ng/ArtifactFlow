"""
Typed-node Quadratic Assignment Procedure utilities.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from itertools import combinations
from typing import ClassVar, Hashable, Literal, Mapping, Sequence, cast

import networkx as nx
import numpy as np
from numpy.typing import NDArray


Array = NDArray[np.float64]
IndexArray = NDArray[np.int64]

Alternative = Literal["greater", "less", "two-sided"]
Alignment = Literal["strict", "union", "intersection"]


__all__ = [
    "Alignment",
    "Alternative",
    "QAP",
    "QAPStudy",
]


@dataclass(frozen=True, slots=True)
class QAPResult:
    """Result of one typed-node QAP comparison."""

    network_a_name: str
    network_b_name: str
    correlation: float
    p_value: float
    permutations: int
    null_distribution: Array
    alternative: Alternative
    alignment: Alignment
    node_count: int
    dyad_count: int

    @property
    def null_mean(self) -> float:
        """Return the mean of the permutation null distribution."""
        return float(np.mean(self.null_distribution))

    @property
    def null_std(self) -> float:
        """Return the sample standard deviation of the null distribution."""
        if self.permutations < 2:
            return 0.0
        return float(np.std(self.null_distribution, ddof=1))

    def is_significant(self, alpha: float = 0.05) -> bool:
        """Return whether the result is statistically significant."""
        _validate_alpha(alpha)
        return self.p_value < alpha

    def interpretation(self, alpha: float = 0.05) -> str:
        """Return a concise interpretation of the comparison."""
        _validate_alpha(alpha)

        if not self.is_significant(alpha):
            return (
                "The observed structural correspondence is not statistically "
                "distinguishable from the type-preserving null distribution."
            )
        if self.alternative == "greater":
            return (
                "The networks have greater structural correspondence than "
                "expected under type-preserving relabeling."
            )
        if self.alternative == "less":
            return (
                "The networks have less structural correspondence than "
                "expected under type-preserving relabeling."
            )

        direction = "positive" if self.correlation >= 0.0 else "negative"
        return (
            f"The networks have an unusually strong {direction} structural "
            "association under the type-preserving null model."
        )

    def summary(self, *, alpha: float = 0.05) -> str:
        """Return a readable multiline summary."""
        _validate_alpha(alpha)
        separator = "=" * 64

        return "\n".join(
            [
                separator,
                f"QAP comparison: {self.network_a_name} vs. {self.network_b_name}",
                separator,
                f"Observed correlation : {self.correlation: .4f}",
                f"Permutation p-value  : {self.p_value: .4f}",
                f"Null mean            : {self.null_mean: .4f}",
                f"Null std. deviation  : {self.null_std: .4f}",
                f"Permutations         : {self.permutations:,}",
                f"Alternative          : {self.alternative}",
                f"Alignment            : {self.alignment}",
                f"Nodes                : {self.node_count:,}",
                f"Dyads                : {self.dyad_count:,}",
                f"Significance level   : {alpha:.3f}",
                f"Significant          : {self.is_significant(alpha)}",
                f"Interpretation       : {self.interpretation(alpha)}",
            ]
        )

    def print_summary(self, *, alpha: float = 0.05) -> None:
        """Print a readable multiline summary."""
        print(self.summary(alpha=alpha))


class QAPStudy:
    """
    Compare several typed-node networks over one global node universe.

    Input graphs are copied, canonicalized, and expanded to the union of all
    canonical node IDs. A node absent from one input is represented there as
    an isolated node, so every pairwise comparison uses the same dyads.
    """

    ALTERNATIVES: ClassVar[tuple[Alternative, ...]] = (
        "greater",
        "less",
        "two-sided",
    )

    def __init__(
        self,
        networks: Mapping[str, nx.Graph],
        *,
        node_type_attr: str = "type",
        weight: str | None = "weight",
        permutations: int = 10_000,
        alternative: Alternative = "greater",
        include_diagonal: bool = False,
        node_mappings: Mapping[
            str, Mapping[Hashable, Hashable] | None
        ]
        | None = None,
        random_state: int | np.random.Generator | None = None,
    ) -> None:
        if len(networks) < 2:
            raise ValueError("QAPStudy requires at least two networks.")
        _validate_options(permutations=permutations, alternative=alternative)

        self._network_names = tuple(networks)
        self._permutations = int(permutations)
        self._alternative: Alternative = alternative
        self._rng = _make_rng(random_state)

        mappings = self._resolve_mappings(node_mappings)
        graphs = [networks[name] for name in self._network_names]
        aligned_graphs, nodes = align_node_universe(
            *graphs,
            node_type_attr=node_type_attr,
            node_mappings=mappings,
        )

        self._graphs = dict(
            zip(self._network_names, aligned_graphs, strict=True)
        )
        self._nodes = tuple(nodes)

        reference_graph = aligned_graphs[0]
        self._dyad_indices = _get_dyad_indices(
            number_of_nodes=len(self._nodes),
            directed=reference_graph.is_directed(),
            include_diagonal=include_diagonal,
        )
        self._type_groups = _make_type_groups(
            reference_graph,
            nodes=self._nodes,
            node_type_attr=node_type_attr,
        )
        self._matrices = {
            name: _to_numpy_array(
                graph,
                nodes=self._nodes,
                weight=weight,
                graph_name=name,
            )
            for name, graph in self._graphs.items()
        }

    @property
    def network_names(self) -> tuple[str, ...]:
        """Return network names in their registered order."""
        return self._network_names

    @property
    def nodelist(self) -> tuple[Hashable, ...]:
        """Return the shared global node order."""
        return self._nodes

    @property
    def node_count(self) -> int:
        """Return the size of the global node universe."""
        return len(self._nodes)

    @property
    def permutations(self) -> int:
        """Return the study's default permutation count."""
        return self._permutations

    @property
    def alternative(self) -> Alternative:
        """Return the study's default alternative hypothesis."""
        return self._alternative

    def compare(
        self,
        network_a_name: str,
        network_b_name: str,
        *,
        permutations: int | None = None,
        alternative: Alternative | None = None,
        random_state: int | np.random.Generator | None = None,
    ) -> QAPResult:
        """Compare two registered networks."""
        self._validate_network_name(network_a_name)
        self._validate_network_name(network_b_name)
        if network_a_name == network_b_name:
            raise ValueError("A network cannot be compared with itself.")

        selected_permutations = (
            self._permutations if permutations is None else permutations
        )
        selected_alternative: Alternative = (
            self._alternative if alternative is None else alternative
        )
        _validate_options(
            permutations=selected_permutations,
            alternative=selected_alternative,
        )
        rng = self._rng if random_state is None else _make_rng(random_state)

        return _run_comparison(
            network_a_name=network_a_name,
            network_b_name=network_b_name,
            matrix_a=self._matrices[network_a_name],
            matrix_b=self._matrices[network_b_name],
            dyad_indices=self._dyad_indices,
            type_groups=self._type_groups,
            permutations=int(selected_permutations),
            alternative=selected_alternative,
            alignment="union",
            rng=rng,
        )

    def compare_all(
        self,
        *,
        permutations: int | None = None,
        alternative: Alternative | None = None,
    ) -> list[QAPResult]:
        """Compare every unique pair of registered networks."""
        return [
            self.compare(
                network_a_name,
                network_b_name,
                permutations=permutations,
                alternative=alternative,
            )
            for network_a_name, network_b_name in combinations(
                self._network_names, 2
            )
        ]

    def get_graph(self, network_name: str, *, copy: bool = True) -> nx.Graph:
        """Return one globally aligned graph."""
        self._validate_network_name(network_name)
        graph = self._graphs[network_name]
        return graph.copy() if copy else graph

    def _resolve_mappings(
        self,
        node_mappings: Mapping[
            str, Mapping[Hashable, Hashable] | None
        ]
        | None,
    ) -> list[Mapping[Hashable, Hashable] | None]:
        if node_mappings is None:
            return [None for _ in self._network_names]

        unknown_names = set(node_mappings) - set(self._network_names)
        if unknown_names:
            raise ValueError(
                "node_mappings contains unknown network names: "
                f"{_format_nodes(unknown_names)}."
            )
        return [node_mappings.get(name) for name in self._network_names]

    def _validate_network_name(self, network_name: str) -> None:
        if network_name not in self._graphs:
            raise KeyError(
                f"Unknown network name {network_name!r}. Available networks: "
                f"{list(self._network_names)!r}."
            )


# Backwards-compatible short name for callers that imported QAP.
QAP = QAPStudy


def qap_compare(
    graph_a: nx.Graph,
    graph_b: nx.Graph,
    *,
    node_type_attr: str = "type",
    weight: str | None = "weight",
    permutations: int = 10_000,
    alternative: Alternative = "greater",
    include_diagonal: bool = False,
    alignment: Alignment = "strict",
    nodelist: Sequence[Hashable] | None = None,
    node_mapping_a: Mapping[Hashable, Hashable] | None = None,
    node_mapping_b: Mapping[Hashable, Hashable] | None = None,
    random_state: int | np.random.Generator | None = None,
) -> QAPResult:
    """Compare two NetworkX graphs using a typed-node QAP test."""
    _validate_graph(graph_a, "graph_a")
    _validate_graph(graph_b, "graph_b")
    if graph_a.is_directed() != graph_b.is_directed():
        raise ValueError("Both graphs must have the same directedness.")
    _validate_options(
        permutations=permutations,
        alternative=alternative,
        alignment=alignment,
    )

    canonical_a = canonicalize_nodes(
        graph_a, node_mapping_a, graph_name="graph_a"
    )
    canonical_b = canonicalize_nodes(
        graph_b, node_mapping_b, graph_name="graph_b"
    )
    aligned_a, aligned_b, default_nodes = _align_graph_pair(
        canonical_a,
        canonical_b,
        node_type_attr=node_type_attr,
        alignment=alignment,
    )
    nodes = _resolve_nodelist(
        aligned_a,
        aligned_b,
        nodelist=nodelist,
        default_nodes=default_nodes,
    )
    _validate_corresponding_types(
        aligned_a,
        aligned_b,
        nodes=nodes,
        node_type_attr=node_type_attr,
    )

    matrix_a = _to_numpy_array(
        aligned_a, nodes=nodes, weight=weight, graph_name="graph_a"
    )
    matrix_b = _to_numpy_array(
        aligned_b, nodes=nodes, weight=weight, graph_name="graph_b"
    )
    dyad_indices = _get_dyad_indices(
        number_of_nodes=len(nodes),
        directed=aligned_a.is_directed(),
        include_diagonal=include_diagonal,
    )
    type_groups = _make_type_groups(
        aligned_a,
        nodes=nodes,
        node_type_attr=node_type_attr,
    )

    return _run_comparison(
        network_a_name="Network A",
        network_b_name="Network B",
        matrix_a=matrix_a,
        matrix_b=matrix_b,
        dyad_indices=dyad_indices,
        type_groups=type_groups,
        permutations=int(permutations),
        alternative=alternative,
        alignment=alignment,
        rng=_make_rng(random_state),
    )


def canonicalize_nodes(
    graph: nx.Graph,
    mapping: Mapping[Hashable, Hashable] | None,
    *,
    graph_name: str = "graph",
) -> nx.Graph:
    """Return a graph copy whose local node IDs use canonical identities."""
    _validate_graph(graph, graph_name)
    if mapping is None:
        return graph.copy()

    unknown_nodes = set(mapping) - set(graph.nodes)
    if unknown_nodes:
        raise ValueError(
            f"{graph_name} mapping contains unknown source nodes: "
            f"{_format_nodes(unknown_nodes)}."
        )

    canonical_ids = [mapping.get(node, node) for node in graph.nodes]
    if len(canonical_ids) != len(set(canonical_ids)):
        collisions = _find_duplicates(canonical_ids)
        raise ValueError(
            f"{graph_name} mapping would merge distinct nodes into "
            f"{_format_nodes(collisions)}. Canonical node mappings must "
            "remain one-to-one."
        )

    return nx.relabel_nodes(graph, dict(mapping), copy=True)


def align_node_universe(
    *graphs: nx.Graph,
    node_type_attr: str = "type",
    node_mappings: Sequence[Mapping[Hashable, Hashable] | None] | None = None,
) -> tuple[list[nx.Graph], list[Hashable]]:
    """Copy graphs and align them to the union of their canonical node IDs."""
    if len(graphs) < 2:
        raise ValueError("At least two graphs are required.")

    if node_mappings is None:
        mappings: list[Mapping[Hashable, Hashable] | None] = [
            None for _ in graphs
        ]
    else:
        if len(node_mappings) != len(graphs):
            raise ValueError(
                "node_mappings must contain one mapping or None for each "
                "input graph."
            )
        mappings = list(node_mappings)

    for index, graph in enumerate(graphs):
        _validate_graph(graph, f"graphs[{index}]")
    directed = graphs[0].is_directed()
    if any(graph.is_directed() != directed for graph in graphs[1:]):
        raise ValueError("All graphs must have the same directedness.")

    canonical_graphs = [
        canonicalize_nodes(
            graph,
            mapping,
            graph_name=f"graphs[{index}]",
        )
        for index, (graph, mapping) in enumerate(
            zip(graphs, mappings, strict=True)
        )
    ]
    nodes = list(
        dict.fromkeys(
            node for graph in canonical_graphs for node in graph.nodes
        )
    )
    node_types = _resolve_node_types(
        canonical_graphs, node_type_attr=node_type_attr
    )

    aligned_graphs: list[nx.Graph] = []
    for graph in canonical_graphs:
        aligned = graph.copy()
        for node in nodes:
            if node not in aligned:
                aligned.add_node(node, **{node_type_attr: node_types[node]})
        aligned_graphs.append(aligned)

    return aligned_graphs, nodes


def _align_graph_pair(
    graph_a: nx.Graph,
    graph_b: nx.Graph,
    *,
    node_type_attr: str,
    alignment: Alignment,
) -> tuple[nx.Graph, nx.Graph, list[Hashable]]:
    nodes_a = set(graph_a.nodes)
    nodes_b = set(graph_b.nodes)

    if alignment == "strict":
        if nodes_a != nodes_b:
            raise ValueError(
                "The graphs must contain identical canonical node IDs when "
                "alignment='strict'. "
                f"Only in graph_a: {_format_nodes(nodes_a - nodes_b)}. "
                f"Only in graph_b: {_format_nodes(nodes_b - nodes_a)}."
            )
        return graph_a.copy(), graph_b.copy(), list(graph_a.nodes)

    if alignment == "intersection":
        shared = nodes_a & nodes_b
        nodes = [node for node in graph_a.nodes if node in shared]
        if len(nodes) < 2:
            raise ValueError(
                "alignment='intersection' retained fewer than two nodes."
            )
        return (
            graph_a.subgraph(nodes).copy(),
            graph_b.subgraph(nodes).copy(),
            nodes,
        )

    aligned, nodes = align_node_universe(
        graph_a, graph_b, node_type_attr=node_type_attr
    )
    return aligned[0], aligned[1], nodes


def _resolve_node_types(
    graphs: Sequence[nx.Graph], *, node_type_attr: str
) -> dict[Hashable, Hashable]:
    node_types: dict[Hashable, Hashable] = {}

    for graph_index, graph in enumerate(graphs):
        for node, attributes in graph.nodes(data=True):
            if node_type_attr not in attributes:
                raise ValueError(
                    f"Node {node!r} in graph {graph_index} has no "
                    f"{node_type_attr!r} attribute."
                )
            node_type = attributes[node_type_attr]
            if node in node_types and node_types[node] != node_type:
                raise ValueError(
                    f"Canonical node {node!r} has inconsistent types across "
                    f"graphs: {node_types[node]!r} and {node_type!r}."
                )
            node_types[node] = node_type

    return node_types


def _resolve_nodelist(
    graph_a: nx.Graph,
    graph_b: nx.Graph,
    *,
    nodelist: Sequence[Hashable] | None,
    default_nodes: Sequence[Hashable],
) -> list[Hashable]:
    if nodelist is None:
        return list(default_nodes)

    nodes = list(nodelist)
    if len(nodes) != len(set(nodes)):
        raise ValueError("nodelist contains duplicate nodes.")

    expected_nodes = set(graph_a.nodes)
    provided_nodes = set(nodes)
    if provided_nodes != expected_nodes:
        raise ValueError(
            "nodelist must contain every aligned node exactly once. "
            f"Missing: {_format_nodes(expected_nodes - provided_nodes)}. "
            f"Unexpected: {_format_nodes(provided_nodes - expected_nodes)}."
        )
    if provided_nodes != set(graph_b.nodes):
        raise ValueError("nodelist is incompatible with graph_b.")
    return nodes


def _validate_corresponding_types(
    graph_a: nx.Graph,
    graph_b: nx.Graph,
    *,
    nodes: Sequence[Hashable],
    node_type_attr: str,
) -> None:
    if len(nodes) < 2:
        raise ValueError("At least two aligned nodes are required.")

    for node in nodes:
        if node_type_attr not in graph_a.nodes[node]:
            raise ValueError(
                f"Node {node!r} in graph_a has no {node_type_attr!r} attribute."
            )
        if node_type_attr not in graph_b.nodes[node]:
            raise ValueError(
                f"Node {node!r} in graph_b has no {node_type_attr!r} attribute."
            )
        type_a = graph_a.nodes[node][node_type_attr]
        type_b = graph_b.nodes[node][node_type_attr]
        if type_a != type_b:
            raise ValueError(
                f"Canonical node {node!r} has inconsistent types: "
                f"{type_a!r} in graph_a and {type_b!r} in graph_b."
            )


def _run_comparison(
    *,
    network_a_name: str,
    network_b_name: str,
    matrix_a: Array,
    matrix_b: Array,
    dyad_indices: tuple[IndexArray, IndexArray],
    type_groups: Mapping[Hashable, IndexArray],
    permutations: int,
    alternative: Alternative,
    alignment: Alignment,
    rng: np.random.Generator,
) -> QAPResult:
    vector_a = matrix_a[dyad_indices]
    vector_b = matrix_b[dyad_indices]
    observed = _pearson_correlation(
        vector_a, vector_b, context="the observed comparison"
    )

    null_distribution = np.empty(permutations, dtype=np.float64)
    for index in range(permutations):
        order = _type_preserving_permutation(
            number_of_nodes=matrix_b.shape[0],
            type_groups=type_groups,
            rng=rng,
        )
        permuted_matrix_b = matrix_b[np.ix_(order, order)]
        null_distribution[index] = _pearson_correlation(
            vector_a,
            permuted_matrix_b[dyad_indices],
            context=f"permutation {index + 1}",
        )

    return QAPResult(
        network_a_name=network_a_name,
        network_b_name=network_b_name,
        correlation=observed,
        p_value=_permutation_p_value(
            observed=observed,
            null_distribution=null_distribution,
            alternative=alternative,
        ),
        permutations=permutations,
        null_distribution=null_distribution,
        alternative=alternative,
        alignment=alignment,
        node_count=matrix_a.shape[0],
        dyad_count=len(vector_a),
    )


def _validate_graph(graph: nx.Graph, graph_name: str) -> None:
    if not isinstance(graph, nx.Graph):
        raise TypeError(f"{graph_name} must be a NetworkX Graph or DiGraph.")
    if graph.is_multigraph():
        raise TypeError(
            f"{graph_name} is a MultiGraph or MultiDiGraph. Aggregate parallel "
            "edges into one weighted edge before running QAP."
        )


def _validate_options(
    *,
    permutations: int,
    alternative: str,
    alignment: str | None = None,
) -> None:
    if isinstance(permutations, bool) or not isinstance(
        permutations, (int, np.integer)
    ):
        raise TypeError("permutations must be an integer.")
    if permutations < 1:
        raise ValueError("permutations must be at least 1.")
    if alternative not in {"greater", "less", "two-sided"}:
        raise ValueError(
            "alternative must be 'greater', 'less', or 'two-sided'."
        )
    if alignment is not None and alignment not in {
        "strict",
        "union",
        "intersection",
    }:
        raise ValueError(
            "alignment must be 'strict', 'union', or 'intersection'."
        )


def _to_numpy_array(
    graph: nx.Graph,
    *,
    nodes: Sequence[Hashable],
    weight: str | None,
    graph_name: str,
) -> Array:
    # NetworkX accepts None to create an unweighted adjacency matrix, but
    # some versions of its type information declare this parameter as str.
    networkx_weight = cast(str, weight)
    matrix = nx.to_numpy_array(
        graph,
        nodelist=list(nodes),
        weight=networkx_weight,
        nonedge=0.0,
        dtype=np.dtype(np.float64),
    )
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"{graph_name} contains NaN or infinite edge weights.")
    return np.asarray(matrix, dtype=np.float64)


def _make_type_groups(
    graph: nx.Graph,
    *,
    nodes: Sequence[Hashable],
    node_type_attr: str,
) -> dict[Hashable, IndexArray]:
    grouped_positions: dict[Hashable, list[int]] = {}
    for position, node in enumerate(nodes):
        node_type = graph.nodes[node][node_type_attr]
        grouped_positions.setdefault(node_type, []).append(position)
    return {
        node_type: np.asarray(positions, dtype=np.int64)
        for node_type, positions in grouped_positions.items()
    }


def _type_preserving_permutation(
    *,
    number_of_nodes: int,
    type_groups: Mapping[Hashable, IndexArray],
    rng: np.random.Generator,
) -> IndexArray:
    order = np.arange(number_of_nodes, dtype=np.int64)
    for positions in type_groups.values():
        order[positions] = rng.permutation(positions)
    return order


def _get_dyad_indices(
    *,
    number_of_nodes: int,
    directed: bool,
    include_diagonal: bool,
) -> tuple[IndexArray, IndexArray]:
    if directed:
        rows, columns = np.indices(
            (number_of_nodes, number_of_nodes), dtype=np.int64
        )
        rows = rows.ravel()
        columns = columns.ravel()
        if not include_diagonal:
            keep = rows != columns
            rows = rows[keep]
            columns = columns[keep]
        return rows, columns

    diagonal_offset = 0 if include_diagonal else 1
    rows, columns = np.triu_indices(number_of_nodes, k=diagonal_offset)
    return (
        np.asarray(rows, dtype=np.int64),
        np.asarray(columns, dtype=np.int64),
    )


def _pearson_correlation(x: Array, y: Array, *, context: str) -> float:
    x_array = np.asarray(x, dtype=np.float64)
    y_array = np.asarray(y, dtype=np.float64)
    if x_array.shape != y_array.shape:
        raise ValueError("Adjacency vectors must have the same shape.")
    if x_array.size < 2:
        raise ValueError("QAP correlation requires at least two dyadic observations.")

    x_centered = x_array - np.mean(x_array)
    y_centered = y_array - np.mean(y_array)
    denominator = np.sqrt(
        np.dot(x_centered, x_centered) * np.dot(y_centered, y_centered)
    )
    if denominator <= np.finfo(np.float64).eps:
        raise ValueError(
            f"QAP correlation is undefined during {context} because at least "
            "one adjacency vector is constant. This can occur when a graph "
            "has no edges, all possible edges, or identical edge weights for "
            "every included dyad."
        )
    return float(np.dot(x_centered, y_centered) / denominator)


def _permutation_p_value(
    *,
    observed: float,
    null_distribution: Array,
    alternative: Alternative,
) -> float:
    if alternative == "greater":
        extreme_count = np.count_nonzero(null_distribution >= observed)
    elif alternative == "less":
        extreme_count = np.count_nonzero(null_distribution <= observed)
    else:
        extreme_count = np.count_nonzero(
            np.abs(null_distribution) >= abs(observed)
        )
    return float((extreme_count + 1) / (len(null_distribution) + 1))


def _make_rng(
    random_state: int | np.random.Generator | None,
) -> np.random.Generator:
    if isinstance(random_state, np.random.Generator):
        return random_state
    return np.random.default_rng(random_state)


def _validate_alpha(alpha: float) -> None:
    if isinstance(alpha, bool) or not isinstance(
        alpha, (int, float, np.integer, np.floating)
    ):
        raise TypeError("alpha must be a real number.")
    if not 0.0 < float(alpha) < 1.0:
        raise ValueError("alpha must be between 0 and 1.")


def _find_duplicates(values: Sequence[Hashable]) -> set[Hashable]:
    seen: set[Hashable] = set()
    duplicates: set[Hashable] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)
    return duplicates


def _format_nodes(nodes: Collection[Hashable]) -> str:
    if not nodes:
        return "none"
    return repr(sorted(nodes, key=repr))
