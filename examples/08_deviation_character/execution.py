"""Compare two Advisor characters after the same observed deviation."""

from artifactflow import Advisor, HOMOPHILIC, NORMATIVE, Project

from workflow import tool_network, workflow


project = Project(workflow, tool_network=tool_network)
normative_advisor = Advisor(project, character=NORMATIVE)
homophilic_advisor = Advisor(project, character=HOMOPHILIC)

# Both Advisors first observe the same normal progress. Each keeps its own
# compact history of the advice it actually showed.
normative_advisor.advise()
homophilic_advisor.advise()
project.record_artifact_available("Start")
project.record_tool_success("Prepare")

normative_proposal = normative_advisor.advise()
homophilic_proposal = homophilic_advisor.advise()
print(
    "Visible preferred option:",
    normative_proposal.options[0].tool_name,
)
assert (
    normative_proposal.options[0].tool_name
    == homophilic_proposal.options[0].tool_name
)

# The LLM instead calls a known tool from outside the preferred Workflow.
# The observer records the fact; it does not need the LLM to confess that it
# deviated.
print("Observed LLM action: Improvised step")
project.record_tool_success("Improvised step")

normative_command = normative_advisor.advise()
homophilic_command = homophilic_advisor.advise()

deviation = normative_command.deviation
if deviation is not None:
    print("Deviation location:", deviation.location)
    print("Previously visible:", deviation.proposed_options)

for label, command in (
    ("Normative order", normative_command),
    ("Homophilic order", homophilic_command),
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
    "\nNormative preference:",
    "restore the proposed Plan before continuing the detour.",
)
print(
    "Homophilic preference:",
    "continue the direction revealed by the LLM first.",
)

snapshot_count = len(normative_advisor.advice_history)
normative_advisor.advise()
print(
    "Repeated advice reused its snapshot:",
    len(normative_advisor.advice_history) == snapshot_count,
)
