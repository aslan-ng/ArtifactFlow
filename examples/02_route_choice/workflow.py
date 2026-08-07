"""Define a workflow with two routes to the same target."""

from artifactflow import Artifact, Tool, Workflow


request = Artifact("Request")
prepared_request = Artifact("Prepared request")
template = Artifact("Template")
custom_draft = Artifact("Custom draft")
report = Artifact("Report")

prepare = Tool("Prepare request", inputs=[request], outputs=[prepared_request])
quick = Tool(
    "Quick route",
    inputs=[prepared_request, template],
    outputs=[report],
)
custom = Tool(
    "Custom route",
    inputs=[prepared_request],
    outputs=[custom_draft],
)
finish_custom = Tool(
    "Finish custom route",
    inputs=[custom_draft],
    outputs=[report],
)

workflow = Workflow()
for tool in (prepare, quick, custom, finish_custom):
    workflow.add_tool(tool)
workflow.starting_artifacts = ["Request"]
workflow.target_artifacts = ["Report"]


if __name__ == "__main__":
    from pathlib import Path

    figure_path = Path(__file__).with_name("workflow.png")
    workflow.savefig(figure_path)
    print("Saved workflow figure:", figure_path)
