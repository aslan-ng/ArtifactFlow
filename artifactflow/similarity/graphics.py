from __future__ import annotations

from collections.abc import Sequence
from math import isfinite
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.figure import Figure

from artifactflow.workflow.workflow import Workflow


class SimilarityGraphics:
    """Plot workflow similarities relative to a reference workflow."""

    def __init__(
        self,
        reference_workflow: Workflow,
        workflows: Sequence[Workflow],
        scores: Sequence[float],
        title: str = "Workflow similarity to reference",
    ) -> None:
        if not isinstance(reference_workflow, Workflow):
            raise TypeError("reference_workflow must be a Workflow.")

        if len(workflows) != len(scores):
            raise ValueError(
                "workflows and scores must have the same length."
            )

        if not workflows:
            raise ValueError("At least one workflow is required.")

        if any(not isinstance(workflow, Workflow) for workflow in workflows):
            raise TypeError("Every workflow must be a Workflow.")

        numeric_scores = tuple(float(score) for score in scores)

        if any(not isfinite(score) for score in numeric_scores):
            raise ValueError("Similarity scores must be finite numbers.")

        self.reference_workflow = reference_workflow
        self.workflows = tuple(workflows)
        self.scores = numeric_scores
        self.title = title

    def _create_figure(self) -> Figure:
        workflow_labels = [
            f"Workflow {index}: {', '.join(workflow.tool_names)}"
            for index, workflow in enumerate(self.workflows, start=1)
        ]
        point_colors = [
            "tab:red"
            if nx.utils.graphs_equal(
                workflow.G,
                self.reference_workflow.G,
            )
            else "tab:blue"
            for workflow in self.workflows
        ]
        y_positions = list(range(len(self.workflows), 0, -1))

        fig, ax = plt.subplots(
            figsize=(14, max(6, 0.55 * len(self.workflows))),
        )
        ax.scatter(
            self.scores,
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
            self.scores,
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

        ax.set_title(self.title)
        ax.set_xlabel("QAP similarity")
        ax.set_yticks(y_positions, labels=workflow_labels)
        ax.set_xlim(-1.05, 1.12)
        ax.grid(axis="x", alpha=0.3)
        ax.legend()
        fig.tight_layout()
        return fig

    def show(self) -> None:
        self._create_figure()
        plt.show()

    def savefig(self, path: str | Path) -> None:
        fig = self._create_figure()

        try:
            fig.savefig(path)
        finally:
            plt.close(fig)
