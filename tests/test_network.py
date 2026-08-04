import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import networkx as nx
import numpy as np

from artifactflow.artifact.artifact import Artifact
from artifactflow.network.network import Network
from artifactflow.tool.tool import Tool


class TestNetworkProducerConflicts(unittest.TestCase):
    def test_lists_artifacts_with_multiple_producers(self):
        shared = Artifact("shared")
        other = Artifact("other")
        network = Network()
        network.add_tool(Tool("producer A", outputs=[shared, other]))
        network.add_tool(Tool("producer B", outputs=[shared]))
        network.add_tool(Tool("consumer", inputs=[shared]))

        self.assertTrue(network.has_producer_conflicts())
        self.assertEqual(
            network.producer_conflicts(),
            {"shared": ["producer A", "producer B"]},
        )

    def test_network_without_multiple_producers_has_no_conflicts(self):
        artifact = Artifact("artifact")
        network = Network()
        network.add_tool(Tool("producer", outputs=[artifact]))
        network.add_tool(Tool("consumer", inputs=[artifact]))

        self.assertFalse(network.has_producer_conflicts())
        self.assertEqual(network.producer_conflicts(), {})

    def test_duplicate_output_on_one_tool_is_not_a_conflict(self):
        artifact = Artifact("artifact")
        network = Network()
        network.add_tool(
            Tool("producer", outputs=[artifact, artifact])
        )

        self.assertFalse(network.has_producer_conflicts())


class TestNetworkGraphics(unittest.TestCase):
    def test_saves_graph_figure(self):
        network = Network()
        network.add_tool(Tool("tool", outputs=[Artifact("artifact")]))

        with TemporaryDirectory() as directory:
            path = Path(directory) / "network.png"

            network.savefig(path)

            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 0)


class TestToolDependencyGraph(unittest.TestCase):
    def test_groups_artifacts_between_the_same_tools(self):
        first = Artifact("first")
        second = Artifact("second")
        network = Network()
        network.add_tool(Tool("producer", outputs=[first, second]))
        network.add_tool(Tool("consumer", inputs=[first, second]))

        graph = network.to_tool_dependency_graph()

        self.assertIsInstance(graph, nx.DiGraph)
        self.assertEqual(
            list(graph.nodes),
            ["producer", "consumer"],
        )
        self.assertEqual(
            graph["producer"]["consumer"]["artifacts"],
            ["first", "second"],
        )

    def test_keeps_tools_without_internal_dependencies(self):
        external = Artifact("external")
        terminal = Artifact("terminal")
        network = Network()
        network.add_tool(
            Tool("standalone", inputs=[external], outputs=[terminal])
        )

        graph = network.to_tool_dependency_graph()

        self.assertEqual(list(graph.nodes), ["standalone"])
        self.assertEqual(list(graph.edges), [])

    def test_expands_multiple_producers_and_consumers(self):
        shared = Artifact("shared")
        network = Network()
        network.add_tool(Tool("producer A", outputs=[shared]))
        network.add_tool(Tool("producer B", outputs=[shared]))
        network.add_tool(Tool("consumer A", inputs=[shared]))
        network.add_tool(Tool("consumer B", inputs=[shared]))

        graph = network.to_tool_dependency_graph()

        self.assertEqual(
            set(graph.edges),
            {
                ("producer A", "consumer A"),
                ("producer A", "consumer B"),
                ("producer B", "consumer A"),
                ("producer B", "consumer B"),
            },
        )
        self.assertTrue(
            all(
                data["artifacts"] == ["shared"]
                for _, _, data in graph.edges(data=True)
            )
        )


class TestToolDependencyMatrix(unittest.TestCase):
    def test_is_binary_and_has_a_one_on_the_diagonal(self):
        first = Artifact("first")
        second = Artifact("second")
        network = Network()
        network.add_tool(Tool("producer", outputs=[first, second]))
        network.add_tool(Tool("consumer", inputs=[first, second]))
        network.add_tool(Tool("isolated"))

        dsm = network.to_tool_dependency_matrix()

        self.assertEqual(
            dsm.tool_names,
            ("producer", "consumer", "isolated"),
        )
        self.assertEqual(
            dsm.tool_indices,
            {
                "producer": 0,
                "consumer": 1,
                "isolated": 2,
            },
        )
        np.testing.assert_array_equal(
            dsm.matrix,
            np.array(
                [
                    [1, 1, 0],
                    [0, 1, 0],
                    [0, 0, 1],
                ],
                dtype=np.int64,
            ),
        )

    def test_places_feedforward_above_and_feedback_below_diagonal(self):
        feedforward = Artifact("feedforward")
        feedback = Artifact("feedback")
        first_tool = Tool(
            "first tool",
            inputs=[feedback],
            outputs=[feedforward],
        )
        second_tool = Tool(
            "second tool",
            inputs=[feedforward],
            outputs=[feedback],
        )
        network = Network()
        network.add_tool(first_tool)
        network.add_tool(second_tool)

        dsm = network.to_tool_dependency_matrix()

        np.testing.assert_array_equal(
            dsm.matrix,
            np.array(
                [
                    [1, 1],
                    [1, 1],
                ],
                dtype=np.int64,
            ),
        )

    def test_empty_network_returns_empty_matrix(self):
        dsm = Network().to_tool_dependency_matrix()

        self.assertEqual(dsm.tool_names, ())
        self.assertEqual(dsm.tool_indices, {})
        self.assertEqual(dsm.matrix.shape, (0, 0))
        self.assertEqual(dsm.matrix.dtype, np.dtype(np.int64))


if __name__ == "__main__":
    unittest.main()
