# ArtifactFlow

ArtifactFlow models tools by the artifacts they consume and produce, discovers
valid routes through those tools, and advises an application what can run next.

ArtifactFlow does not execute tools. The embedding application maps each tool
name to its own runtime—a local function, service, job, or agent tool—and
records the observed result.

## Install

ArtifactFlow requires Python 3.10 or later.

```bash
pip install -e .
```

## Quickstart

```python
from artifactflow import Advisor, Artifact, Project, Tool, Workflow

request = Artifact("Request")
draft = Artifact("Draft")
result = Artifact("Result")

workflow = Workflow()
workflow.add_tool(Tool("Write", inputs=[request], outputs=[draft]))
workflow.add_tool(Tool("Publish", inputs=[draft], outputs=[result]))
workflow.starting_artifacts = ["Request"]
workflow.target_artifacts = ["Result"]

project = Project(workflow)
advisor = Advisor(project)

command = advisor.advise()
option = command.options[0]

for artifact_name in option.missing_artifacts:
    project.record_artifact_available(artifact_name)

project.record_tool_success(option.tool_name)
command = advisor.advise()
```

`command.status` is `COMMAND`, `COMPLETE`, or `BLOCKED`. Only options directly
inside `command.options` are executable; nested continuations are previews.

## Core model

- `Artifact` names a value or file that can be consumed or produced.
- `Tool` declares its artifact inputs and outputs.
- `ToolNetwork` is the wider set of available tools.
- `Workflow` defines one bounded process inside that network.
- `Plan` is a discovered, target-reaching route through a Workflow.
- `Project` combines a Workflow with observed execution history.
- `Advisor` replays that history and returns the next valid options.

## Embedding lifecycle

The application owns tool execution:

1. Call `advisor.advise()`.
2. Select one root option.
3. Obtain any `option.missing_artifacts`.
4. Invoke the application tool identified by `option.tool_name`.
5. Record the exact result with `record_tool_success()` or
   `record_tool_failure()`.
6. Ask the Advisor again.

`option.input_artifacts` contains exact `(artifact name, version)` bindings.
Use those versions when an option restores an earlier checkpoint. Convert tool
results into `ArtifactOutput` objects when payloads or file references matter.

## State and persistence

`ExecutionLog` is the append-only factual record of available artifacts, tool
successes, tool failures, and target acceptance. `AdviceHistory` separately
records which options an Advisor showed at each observed state.

Both histories are currently in-memory objects. An application that persists
projects must store and reconstruct:

- the Workflow and ToolNetwork definitions;
- the ordered execution events and artifact versions;
- the AdviceHistory for that Project; and
- the Advisor configuration.

ArtifactFlow does not currently define a stable JSON persistence format.
Stored artifact values must therefore follow the embedding application's own
serialization rules.

## Runtime guarantees

- Record each observation exactly once and in execution order.
- Use one writer per Project, or provide external locking.
- Repeating `advise()` with unchanged state and configuration is safe.
- ArtifactFlow does not deduplicate externally delivered events; the embedding
  application is responsible for idempotency.
- Keep an AdviceHistory with its original Project and Advisor configuration.
- Structured command fields control behavior; `message` is only a summary.

Invalid definitions or observations raise `TypeError`, `ValueError`, or
`KeyError`. Applications should validate at their boundary and translate these
exceptions into their own error model.

## Guides

- [Examples](examples/README.md)
- [Advisor response reference](artifactflow/advisor/README.md)

Run the test suite with:

```bash
python -m unittest discover -s tests -p 'test_*.py'
```
