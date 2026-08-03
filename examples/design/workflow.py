import random

import matplotlib.pyplot as plt

from tools import tool_network

filtered_tool_network = tool_network.filter(
    starting_artifacts=["CAD File"],
    target_artifacts=["CAD File"],
)
workflows = filtered_tool_network.discover()

if not workflows:
    raise RuntimeError("No workflows were discovered.")

reference_workflow = random.Random(42).choice(workflows)
#reference_workflow.show()
similar_workflows = filtered_tool_network.similar_workflows(
    workflow=reference_workflow,
)


if __name__ == "__main__":
    print(
        "Reference workflow:",
        reference_workflow.tool_names,
    )

    similarity_scores = [
        similarity
        for _, similarity in similar_workflows
    ]
    workflow_labels = [
        f"Workflow {index}: {', '.join(candidate.tool_names)}"
        for index, (candidate, _) in enumerate(
            similar_workflows,
            start=1,
        )
    ]
    point_colors = [
        "tab:red"
        if set(candidate.tool_names) == set(reference_workflow.tool_names)
        else "tab:blue"
        for candidate, _ in similar_workflows
    ]
    y_positions = list(range(len(similar_workflows), 0, -1))

    _, ax = plt.subplots(
        figsize=(11, max(4, 0.45 * len(similar_workflows))),
    )
    ax.scatter(
        similarity_scores,
        y_positions,
        color=point_colors,
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

    ax.set_title("Design workflow similarity to a random reference")
    ax.set_xlabel("QAP similarity")
    ax.set_yticks(y_positions, labels=workflow_labels)
    ax.set_xlim(-1.05, 1.12)
    ax.grid(axis="x", alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.show()
