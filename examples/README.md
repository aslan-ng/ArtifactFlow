# ArtifactFlow examples

These examples show how an application, an LLM, or a simulation can ask an
ArtifactFlow `Advisor` what to do next.

ArtifactFlow does not execute tools. The caller asks for advice, performs one
external action, and reports the observed result in the next call:

```python
command = advisor.advise()
command = advisor.advise(ArtifactAvailable("Brief"))
command = advisor.advise(ToolSucceeded("Write draft"))
command = advisor.advise(ToolFailed("Review draft", "service timeout"))
command = advisor.advise(TargetsAccepted())
```

The report is a fact that has already been observed, not an instruction or an
intention. `advise(report)` validates and records that event before returning
fresh advice. Calling `advise()` without a report is read-only, so repeated
calls return the same advice while the project log is unchanged.

These examples use the single-call reporting style intended for an eventual
MCP wrapper. `Project` and `User` also provide direct recording methods for
other applications, but the same event should never be recorded through both
paths.

## Suggested reading order

1. `01_linear_workflow/` — learn the smallest interaction loop and automatic
   completion of a linear workflow.
2. `02_route_choice/` — inspect multiple routes several steps ahead and see a
   route-dependent artifact before choosing that route.
3. `03_middle_cycle/` — inspect a bounded preview of a middle cycle, repeat it,
   and then take its exit.
4. `04_target_cycle/` — produce several target candidates and explicitly
   accept the third one.
5. `05_retry_and_alternative/` — see a retry and a sibling alternative at the
   same time.
6. `06_backtrack/` — exhaust a nested branch and return to an earlier decision
   point.
7. `07_blocked/` — limit the Advisor to one visible option, exhaust every
   route, and receive `BLOCKED`.

Each example separates two concerns:

- `workflow.py` defines the artifacts, tools, and workflow. Running it saves
  `workflow.png` in the same folder.
- `execution.py` imports that workflow and demonstrates the advice loop.

For example, run both parts of the linear example from the repository root:

```bash
python examples/01_linear_workflow/workflow.py
python examples/01_linear_workflow/execution.py
```

## Controlling how much the Advisor shows

The two planning controls are independent:

```python
advisor = Advisor(
    project,
    lookahead_depth=3,
    max_options=2,
)
```

`lookahead_depth` counts tool calls. Depth 1, the default, shows only tools
that can run now. Greater depths recursively populate each option's
`continuations`. Only options directly inside `command.options` are
executable; nested continuations are previews that assume their parent tools
succeed.

`max_options` limits the number of alternatives shown at every visible
decision. `None`, the default, shows all alternatives. If the limit is five
and only three options exist, all three are returned. Asking again without a
report is not pagination: it returns the same options.

Options use deterministic workflow order. With a very small limit, an option
later in that order can remain hidden—for example, a cycle exit ordered after
its repeat option. Use `None` when every choice must remain visible; a future
ranking policy can address other experimental selection strategies.

The Advisor marks omitted information explicitly:

- `command.options_truncated` means root alternatives were hidden by
  `max_options`.
- `option.options_truncated` means some of that option's continuation choices
  were hidden.
- `option.has_more` means the depth boundary was reached while more workflow
  steps remain.

These markers mean "the preview stopped here," not "the workflow ends here."
Cycles are therefore safe: they are unfolded only as far as the configured
depth.

## Reading an option

Each `ToolOption` reports:

- `tool_name`: the MCP tool to call.
- `action`: `RUN`, `RETRY`, or `ALTERNATIVE`.
- `missing_artifacts`: inputs not available along this route.
- `continuations`: possible tools after this tool succeeds.
- `outcome`: `CONTINUE`, `TARGETS_READY`, `COMPLETE`, or `DEAD_END`.
- `has_more` and `options_truncated`: preview boundary markers.

A missing artifact on a root option must be obtained before calling that tool.
A missing artifact on a nested continuation may be needed later, but only if
that route is followed. Artifacts created by earlier tools in the same preview
are not reported as missing from their consumers.

## Status, recovery, and completion

- `COMMAND`: choose a normal root tool.
- `RECOVERY`: choose a retry or an available alternative.
- `COMPLETE`: the project has completed.
- `BLOCKED`: every available route and retry has been exhausted.

After a first failure, the failed tool's retry is ordered first and unchecked
sibling options follow it. After the branch is exhausted, alternatives from
the nearest earlier decision point become available. Every option includes
the same success-based lookahead preview; future failures are handled only if
they actually occur.

A linear target completes automatically. If a cycle can create another target
candidate, `command.target_acceptance_required` is true. The caller may then
report `TargetsAccepted()` or choose a root continuation to create a new
candidate.

This lightweight API intentionally uses tool names instead of option IDs. It
assumes tool names are unique, execution is sequential, and reports arrive
once and in order.
