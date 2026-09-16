"""
Compare two guidance policies after the same observed deviation.
"""

from artifactflow import (
    Advisor,
    OPPORTUNISTIC,
    Project,
    WORKFLOW_ADHERENT,
)

from workflow import tool_network, workflow


project = Project(workflow, tool_network=tool_network)
workflow_adherent_advisor = Advisor(project, policy=WORKFLOW_ADHERENT)
opportunistic_advisor = Advisor(project, policy=OPPORTUNISTIC)

# Both Advisors first observe the same normal progress. Each keeps its own
# compact history of the advice it actually showed.
workflow_adherent_advisor.advise()
opportunistic_advisor.advise()
project.record_artifact_available("Start")
project.record_tool_success("Prepare")

workflow_adherent_proposal = workflow_adherent_advisor.advise()
opportunistic_proposal = opportunistic_advisor.advise()
print(
    "Visible preferred option:",
    workflow_adherent_proposal.options[0].tool_name,
)
assert (
    workflow_adherent_proposal.options[0].tool_name
    == opportunistic_proposal.options[0].tool_name
)

# The LLM instead calls a known tool from outside the preferred Workflow.
# The observer records the fact; it does not need the LLM to confess that it
# deviated.
print("Observed LLM action: Improvised step")
project.record_tool_success("Improvised step")

workflow_adherent_command = workflow_adherent_advisor.advise()
opportunistic_command = opportunistic_advisor.advise()

deviation = workflow_adherent_command.deviation
if deviation is not None:
    print("Deviation location:", deviation.location)
    print("Previously visible:", deviation.proposed_options)

for label, command in (
    ("Workflow-adherent order", workflow_adherent_command),
    ("Opportunistic order", opportunistic_command),
):
    print("\n" + label + ":")
    for option in command.options:
        print(
            " -",
            option.tool_name,
            "| scope:",
            option.scope,
            "| transition:",
            option.transition,
        )

print(
    "\nWorkflow-adherent preference:",
    "restore the proposed Plan before continuing the detour.",
)
print(
    "Opportunistic preference:",
    "continue the direction revealed by the LLM first.",
)

snapshot_count = len(workflow_adherent_advisor.advice_history)
workflow_adherent_advisor.advise()
print(
    "Repeated advice reused its snapshot:",
    len(workflow_adherent_advisor.advice_history) == snapshot_count,
)
