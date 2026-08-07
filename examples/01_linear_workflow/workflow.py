"""Define the linear workflow used by this example."""

from artifactflow import Artifact, Tool, Workflow


""" Setup """
brief = Artifact("Brief")
outline = Artifact("Outline")
final_report = Artifact("Final report")

make_outline = Tool("Make outline", inputs=[brief], outputs=[outline])
write_report = Tool(
    "Write report",
    inputs=[outline],
    outputs=[final_report],
)

workflow = Workflow()
workflow.add_tool(make_outline)
workflow.add_tool(write_report)
workflow.starting_artifacts = ["Brief"]
workflow.target_artifacts = ["Final report"]


if __name__ == "__main__":
    from pathlib import Path

    figure_path = Path(__file__).with_name("workflow.png")
    workflow.savefig(figure_path)
    print("Saved workflow figure:", figure_path)
