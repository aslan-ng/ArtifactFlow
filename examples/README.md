# Examples

These examples show how to define workflows, record observed execution, and
request advice. Run commands from the repository root.

## Suggested order

| Example | Demonstrates |
| --- | --- |
| `01_linear_workflow` | Minimal advice and execution loop |
| `02_route_choice` | Alternative routes and lookahead |
| `03_middle_cycle` | Repeating a cycle before taking its exit |
| `04_target_cycle` | Producing and accepting target candidates |
| `05_retry_and_alternative` | Retrying a failed tool or choosing a sibling route |
| `06_backtrack` | Exhausting a branch and restoring an earlier decision |
| `07_blocked` | Exhausting all routes and receiving `BLOCKED` |
| `08_deviation_policy` | Responding to execution outside the proposed Plan |
| `09_design` | Discovering and comparing workflows in a ToolNetwork |
| `10_resume_from_history` | Loading existing execution events and advising from the middle |

Most orchestration examples contain:

- `workflow.py`, which defines the artifacts, tools, and Workflow;
- `execution.py`, which simulates an application recording tool results and
  consulting the Advisor.

Example 09 is a design exploration: `tools.py` defines a ToolNetwork and
`workflow.py` discovers and compares candidate Workflows.

## Run an example

```bash
python examples/01_linear_workflow/workflow.py
python examples/01_linear_workflow/execution.py
```

The history example starts with previously recorded events:

```bash
python examples/10_resume_from_history/execution.py
```

Workflow scripts may save diagrams in their example directory.

For command statuses, option fields, lookahead, retries, cycles, and recovery,
see the [Advisor response reference](../artifactflow/advisor/README.md).
