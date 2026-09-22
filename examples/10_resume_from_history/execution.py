"""
Load an existing execution history and ask for advice mid-project.

An application-specific adapter would normally deserialize database, MCP, or
LLM tool-call records into these canonical events. This example constructs the
same records directly so every part of the resume process is visible.
"""

from artifactflow import (
    Advisor,
    ArtifactAvailable,
    ArtifactOutput,
    ArtifactVersion,
    ExecutionLog,
    Project,
    ToolFailed,
    ToolSucceeded,
)

from workflow import workflow


def load_execution_log() -> ExecutionLog:
    """Reconstruct an ExecutionLog from three persisted observations."""
    brief_v1 = ArtifactVersion(
        artifact_name="Brief",
        version=1,
        value="Explain why the launch date changed.",
    )
    draft_v1 = ArtifactVersion(
        artifact_name="Draft",
        version=1,
        value="The launch moved after additional reliability testing.",
    )
    stored_events = (
        ArtifactAvailable(brief_v1),
        ToolSucceeded(
            tool_name="Write draft",
            inputs=(brief_v1,),
            outputs=(draft_v1,),
        ),
        ToolFailed(
            tool_name="Automated review",
            reason="review service timed out",
            inputs=(draft_v1,),
        ),
    )

    execution_log = ExecutionLog()
    for event in stored_events:
        execution_log.append(event)
    return execution_log


execution_log = load_execution_log()
project = Project(workflow, execution_log=execution_log)

print("Loaded execution events:")
for position, event in enumerate(project.events, start=1):
    print(" ", position, type(event).__name__)

print("Reconstructed successful tools:", project.state.successful_tools)
print("Reconstructed failed attempts:", project.state.failed_attempts)
print("Latest Draft version:", project.latest_artifact("Draft").version)

# The Advisor replays all three events on its first consultation. It does not
# ask to obtain the Brief or run Write draft again.
advisor = Advisor(project)
command = advisor.advise()

print("\nFirst advice after loading history:")
for option in command.options:
    print(
        " ",
        option.action,
        option.tool_name,
        "using",
        option.input_artifacts,
    )

assert tuple(
    (option.action, option.tool_name)
    for option in command.options
) == (
    ("RETRY", "Automated review"),
    ("ALTERNATIVE", "Human review"),
)

# AdviceHistory is separate from ExecutionLog. The first call above records
# what the Advisor showed after the three already-loaded execution events.
snapshot = advisor.advice_history.latest()
assert snapshot is not None
print("\nAdvice snapshot event position:", snapshot.event_position)
print("Advice snapshot visible tools:", snapshot.visible_root_tools)

# Continue from the loaded state using the alternative route.
draft_v1 = execution_log.artifact("Draft", 1)
project.record_tool_success(
    "Human review",
    inputs=(draft_v1,),
    outputs=(
        ArtifactOutput(
            "Approved report",
            value="Approved after human review.",
        ),
    ),
)
completion = advisor.advise()
print("\n" + completion.status + ":", completion.message)
assert completion.status == "COMPLETE"
