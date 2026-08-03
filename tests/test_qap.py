import unittest

import networkx as nx
import numpy as np

from artifactflow.tool.examples import tool_1, tool_2, tool_3, tool_4
from artifactflow.workflow.tool_network import ToolNetwork
from artifactflow.utils.qap.qap import QAP, QAPStudy, qap_compare


def make_tool_network(*tools):
    network = ToolNetwork()
    for tool in tools:
        network.add_tool(tool)
    return network


class TestQAPStudy(unittest.TestCase):
    def setUp(self):
        self.network_1 = make_tool_network(tool_1, tool_2, tool_3, tool_4)
        self.network_2 = make_tool_network(tool_1, tool_2, tool_3)
        self.network_3 = make_tool_network(tool_1, tool_4)

    def make_study(self, *, seed=42):
        return QAPStudy(
            networks={
                "Tool Network 1": self.network_1.G,
                "Tool Network 2": self.network_2.G,
                "Tool Network 3": self.network_3.G,
            },
            permutations=50,
            alternative="greater",
            random_state=seed,
        )

    def test_example_aligns_all_networks_and_compares_every_pair(self):
        original_node_counts = [
            len(self.network_1.G),
            len(self.network_2.G),
            len(self.network_3.G),
        ]
        study = self.make_study()
        results = study.compare_all()

        self.assertEqual(study.node_count, 9)
        self.assertEqual(len(results), 3)
        self.assertEqual(
            [
                (result.network_a_name, result.network_b_name)
                for result in results
            ],
            [
                ("Tool Network 1", "Tool Network 2"),
                ("Tool Network 1", "Tool Network 3"),
                ("Tool Network 2", "Tool Network 3"),
            ],
        )
        self.assertTrue(all(result.node_count == 9 for result in results))
        self.assertTrue(all(result.dyad_count == 72 for result in results))
        self.assertTrue(all(0.0 < result.p_value <= 1.0 for result in results))
        self.assertEqual(
            original_node_counts,
            [
                len(self.network_1.G),
                len(self.network_2.G),
                len(self.network_3.G),
            ],
        )

        expected_nodes = set(study.nodelist)
        for name in study.network_names:
            self.assertEqual(set(study.get_graph(name)), expected_nodes)

    def test_seed_is_reproducible(self):
        first = self.make_study(seed=123).compare_all()
        second = self.make_study(seed=123).compare_all()
        for result_a, result_b in zip(first, second, strict=True):
            np.testing.assert_array_equal(
                result_a.null_distribution,
                result_b.null_distribution,
            )
            self.assertEqual(result_a.p_value, result_b.p_value)

    def test_qap_remains_an_alias(self):
        self.assertIs(QAP, QAPStudy)

    def test_inconsistent_node_types_are_rejected(self):
        graph_a = nx.DiGraph()
        graph_b = nx.DiGraph()
        graph_a.add_node("shared", type="tool")
        graph_b.add_node("shared", type="artifact")
        graph_a.add_node("other", type="artifact")
        graph_b.add_node("other", type="artifact")

        with self.assertRaisesRegex(ValueError, "inconsistent types"):
            QAPStudy({"a": graph_a, "b": graph_b}, permutations=1)


class TestQAPCompare(unittest.TestCase):
    def test_functional_api_still_works(self):
        graph_a = nx.DiGraph()
        graph_b = nx.DiGraph()
        for graph in (graph_a, graph_b):
            graph.add_nodes_from(
                [
                    ("tool-a", {"kind": "tool"}),
                    ("tool-b", {"kind": "tool"}),
                    ("artifact-a", {"kind": "artifact"}),
                    ("artifact-b", {"kind": "artifact"}),
                ]
            )
        graph_a.add_edges_from(
            [("artifact-a", "tool-a"), ("tool-a", "artifact-b")]
        )
        graph_b.add_edges_from(
            [
                ("artifact-a", "tool-a"),
                ("tool-b", "artifact-b"),
                ("artifact-b", "tool-a"),
            ]
        )

        result = qap_compare(
            graph_a,
            graph_b,
            node_type_attr="kind",
            permutations=20,
            alternative="two-sided",
            random_state=7,
        )

        self.assertEqual(result.node_count, 4)
        self.assertEqual(result.dyad_count, 12)
        self.assertEqual(result.alignment, "strict")
        self.assertEqual(result.null_distribution.shape, (20,))


if __name__ == "__main__":
    unittest.main()
