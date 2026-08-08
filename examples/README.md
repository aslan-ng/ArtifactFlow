# ArtifactFlow examples

These examples show how an application, an LLM, or a simulation can ask an
ArtifactFlow `Advisor` what to do next.

ArtifactFlow does not execute tools or depend on the LLM remembering to report
its actions. An observer records facts on the `Project`; whenever advice is
requested, the Advisor reconstructs the current state from that history:

```python
command = advisor.advise()

project.record_artifact_available("Brief")
project.record_tool_success("Write draft")
command = advisor.advise()

project.record_tool_failure("Review draft", "service timeout")
command = advisor.advise()

if command.target_acceptance_required:
    project.record_target_acceptance()
    command = advisor.advise()
```

The recording calls above simulate an observer. In a production integration, a
raw LLM or MCP log adapter would make the same records from actual tool results,
not from natural-language claims made by the LLM. `advise()` is read-only, so
repeated calls return the same advice while the execution log is unchanged.

The Advisor does not need to be called after every observation. If several
valid steps happen before the next consultation, it replays all of them:

```python
# Assume these are consecutive tools on the selected workflow route.
project.record_tool_success("Prepare data")
project.record_tool_success("Run analysis")

# This catches up with both successful calls.
command = advisor.advise()
```

This prevents a missed consultation from permanently breaking the connection.
The history must still contain each observed fact exactly once and in execution
order. `Project` recording methods are convenient for examples and simulations;
raw-log adapters should write the equivalent canonical observations. `User`
records human or externally supplied artifacts and target acceptance.

## Artifact versions

The execution log is append-only. Recording the same artifact name again
creates another version rather than overwriting the earlier value or file.
For example:

```python
first = project.record_artifact_available("Temperature", value=288.15)
second = project.record_artifact_available("Temperature", value=290.10)

assert first.version == 1
assert second.version == 2
assert project.latest_artifact("Temperature") == second
```

Tool observations can also record their exact input versions and output values
or files. The examples omit those payloads to stay focused on orchestration;
the Project creates payload-free versions from the workflow definition. During
recovery, the Advisor uses the newest versions valid on the restored route,
which is not necessarily the newest version anywhere in the factual history.

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
candidate, `command.target_acceptance_required` is true. The observer may then
record `project.record_target_acceptance()` before asking again, or the caller
may choose a root continuation to create a new candidate.

This lightweight API intentionally uses tool names instead of option IDs. It
assumes tool names are unique, execution is sequential, and observations arrive
once and in order.
