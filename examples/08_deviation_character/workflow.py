"""Define a preferred workflow inside a wider tool network."""

from artifactflow import Artifact, Tool, Workflow


start = Artifact("Start")
prepared = Artifact("Prepared")
preferred_draft = Artifact("Preferred draft")
improvised_draft = Artifact("Improvised draft")
result = Artifact("Result")

prepare = Tool("Prepare", inputs=[start], outputs=[prepared])
preferred_step = Tool(
    "Preferred step",
    inputs=[prepared],
    outputs=[preferred_draft],
)
preferred_finish = Tool(
    "Preferred finish",
    inputs=[preferred_draft],
    outputs=[result],
)

workflow = Workflow()
for tool in (prepare, preferred_step, preferred_finish):
    workflow.add_tool(tool)
workflow.starting_artifacts = ["Start"]
workflow.target_artifacts = ["Result"]

# These tools are technically available, but are not part of the preferred
# workflow. The observer can still see if the LLM calls either one.
improvised_step = Tool(
    "Improvised step",
    inputs=[prepared],
    outputs=[improvised_draft],
)
improvised_finish = Tool(
    "Improvised finish",
    inputs=[improvised_draft],
    outputs=[result],
)

tool_network = workflow.to_tool_network()
tool_network.add_tool(improvised_step)
tool_network.add_tool(improvised_finish)


if __name__ == "__main__":
    from pathlib import Path

    workflow_path = Path(__file__).with_name("workflow.png")
    network_path = Path(__file__).with_name("tool_network.png")
    workflow.savefig(workflow_path)
    tool_network.savefig(network_path)
    print("Saved preferred workflow figure:", workflow_path)
    print("Saved complete tool network figure:", network_path)
