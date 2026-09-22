from pathlib import Path

from artifactflow.similarity.graphics import SimilarityGraphics
from tools import tool_network


discovery_boundary = dict(
    starting_artifacts=["CAD File"],
    target_artifacts=["CAD File"],
)
workflows = tool_network.discover(**discovery_boundary)

if not workflows:
    raise RuntimeError("No workflows were discovered.")

reference_workflow = workflows[3]
#reference_workflow.show()
similar_workflows = tool_network.similar_workflows(
    workflow=reference_workflow,
    **discovery_boundary,
)
candidate_workflows = [
    workflow
    for workflow, _ in similar_workflows
]
similarity_scores = [
    score
    for _, score in similar_workflows
]
similarity_graphics = SimilarityGraphics(
    reference_workflow=reference_workflow,
    workflows=candidate_workflows,
    scores=similarity_scores,
    title="Design workflow similarity to a random reference",
)


if __name__ == "__main__":
    print(
        "Reference workflow:",
        reference_workflow.tool_names,
    )

    output_path = Path(__file__).parent / "results" / "workflow_similarity.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    similarity_graphics.savefig(output_path)
    similarity_graphics.show()
