"""Define a workflow with nested choices for backtracking."""

from artifactflow import Artifact, Tool, Workflow


request = Artifact("Request")
prepared = Artifact("Prepared request")
detailed_input = Artifact("Detailed input")
approval_note = Artifact("Approval note")
result = Artifact("Result")

prepare = Tool("Prepare", inputs=[request], outputs=[prepared])
detailed = Tool(
    "Detailed route",
    inputs=[prepared],
    outputs=[detailed_input],
)
concise = Tool(
    "Concise route",
    inputs=[prepared, approval_note],
    outputs=[result],
)
standard = Tool("Standard route", inputs=[prepared], outputs=[result])
engine_one = Tool(
    "Detailed engine one",
    inputs=[detailed_input],
    outputs=[result],
)
engine_two = Tool(
    "Detailed engine two",
    inputs=[detailed_input],
    outputs=[result],
)

workflow = Workflow()
for tool in (
    prepare,
    detailed,
    concise,
    standard,
    engine_one,
    engine_two,
):
    workflow.add_tool(tool)
workflow.starting_artifacts = ["Request"]
workflow.target_artifacts = ["Result"]


if __name__ == "__main__":
    from pathlib import Path

    figure_path = Path(__file__).with_name("workflow.png")
    workflow.savefig(figure_path)
    print("Saved workflow figure:", figure_path)
