import unittest

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


if __name__ == "__main__":
    unittest.main()
