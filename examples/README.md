# ArtifactFlow examples

These examples show how an application, an LLM, or a simulation can ask an
ArtifactFlow `Advisor` what to do next.

ArtifactFlow does not execute tools. After some external caller executes a
tool, it records exactly one observed result:

```python
project.record_tool_success("Tool name")
project.record_tool_failure("Tool name", "reason")
```

Similarly, `User` represents a human or simulated user supplying an artifact
or accepting a target candidate. An MCP wrapper may record the same events
after observing them in a chat interface.

## Suggested reading order

1. `01_linear_workflow/` — provide bootstrap artifacts in advance and run a
   linear workflow to automatic completion.
2. `02_route_choice/` — compare alternative routes and provide a conditional
   bootstrap artifact only after choosing the route that needs it.
3. `03_middle_cycle/` — repeat a cycle in the middle of a workflow, then take
   the linear exit.
4. `04_target_cycle/` — produce several target candidates and accept the third
   one.
5. `05_retry_and_alternative/` — retry a failed tool once, then use its sibling
   alternative.
6. `06_backtrack/` — exhaust a nested branch and return to an earlier decision
   point.
7. `07_blocked/` — exhaust every route and receive `BLOCKED`.

Each example separates two concerns:

- `workflow.py` defines only the artifacts, tools, and workflow. Running it
  saves `workflow.png` in the same folder.
- `execution.py` imports that workflow and demonstrates how a caller interacts
  with `Project`, `Advisor`, and `User`.

For example, run both parts of the linear example from the repository root:

```bash
python examples/01_linear_workflow/workflow.py
python examples/01_linear_workflow/execution.py
```

## What the command statuses mean

- `COMMAND`: choose a normal next tool.
- `RECOVERY`: retry once or choose an alternative route.
- `COMPLETE`: the target is complete.
- `BLOCKED`: every available route and retry has been exhausted.

`required_artifacts` means “provide these before this tool.”
`suggested_artifacts` means “these are likely to be needed later.” Multiple
tool options are alternative routes, not parallel work.

“Retry once” means at most two attempts for one tool at one decision point.
The Project keeps the complete historical record, including successful work
on an abandoned branch. The Advisor separately restores the active route when
it backtracks.
