import matplotlib.pyplot as plt

from artifactflow.tool_network.examples.example_3 import tool_network
from artifactflow.workflow.examples.example_1 import workflow


workflows = tool_network.similar_workflows(
    workflow=workflow,
)
similarity_scores = [
    similarity
    for _, similarity in workflows
]
workflow_labels = [
    f"Workflow {index}: {', '.join(candidate.tool_names)}"
    for index, (candidate, _) in enumerate(workflows, start=1)
]


if __name__ == "__main__":
    y_positions = list(range(len(workflows), 0, -1))
    _, ax = plt.subplots(
        figsize=(10, max(4, 0.45 * len(workflows))),
    )
    ax.scatter(
        similarity_scores,
        y_positions,
        color="tab:orange",
        s=70,
        zorder=3,
    )
    ax.axvline(
        1.0,
        color="tab:red",
        linestyle="--",
        label="Reference workflow",
    )
    for score, y_position in zip(
        similarity_scores,
        y_positions,
        strict=True,
    ):
        ax.annotate(
            f"{score:.3f}",
            (score, y_position),
            xytext=(7, 0),
            textcoords="offset points",
            va="center",
        )

    ax.set_title("Filtered workflow similarity to reference")
    ax.set_xlabel("QAP similarity")
    ax.set_yticks(y_positions, labels=workflow_labels)
    ax.set_xlim(-1.05, 1.12)
    ax.grid(axis="x", alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.show()
