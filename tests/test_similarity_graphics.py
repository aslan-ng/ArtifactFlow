import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from artifactflow.artifact.artifact import Artifact
from artifactflow.similarity.graphics import SimilarityGraphics
from artifactflow.tool.tool import Tool
from artifactflow.workflow.workflow import Workflow


class TestSimilarityGraphics(unittest.TestCase):
    @staticmethod
    def make_workflow(name: str) -> Workflow:
        workflow = Workflow()
        workflow.add_tool(
            Tool(name, outputs=[Artifact(f"{name} output")])
        )
        return workflow

    def test_saves_similarity_figure(self):
        reference = self.make_workflow("reference")
        candidate = self.make_workflow("candidate")
        graphics = SimilarityGraphics(
            reference_workflow=reference,
            workflows=[reference, candidate],
            scores=[1.0, 0.5],
        )

        with TemporaryDirectory() as directory:
            path = Path(directory) / "similarity.png"

            graphics.savefig(path)

            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 0)

    def test_rejects_different_workflow_and_score_counts(self):
        reference = self.make_workflow("reference")

        with self.assertRaisesRegex(ValueError, "same length"):
            SimilarityGraphics(
                reference_workflow=reference,
                workflows=[reference],
                scores=[],
            )


if __name__ == "__main__":
    unittest.main()
