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
not from natural-language claims made by the LLM. `advise()` never changes the
factual execution log. Repeated calls return the same advice while that log and
the Advisor configuration are unchanged.

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

## Why the Advisor remembers its own advice

The execution log records what happened, but it cannot say what the Advisor
previously showed. Each Advisor therefore has an `AdviceHistory` in addition to
the Project's factual `ExecutionLog`:

```python
command = advisor.advise()
snapshot = advisor.advice_history.latest()

if snapshot is not None:
    print(snapshot.event_position)
    print(snapshot.visible_root_tools)
```

An immutable advice snapshot stores the number of project events already seen,
the Advisor configuration, the visible root tools, and compact signatures of
the Plans supporting each tool. Repeating `advise()` at the same project state
and configuration reuses the same snapshot instead of creating a duplicate.
This lets the Advisor recognize a later action as following or deviating from
what was actually visible, including when `max_options` hid other valid routes.
Keep that history for the lifetime of one Project run. If an integration
recreates the Advisor between MCP calls, inject the same history again:

```python
history = advisor.advice_history
advisor = Advisor(
    project,
    advice_history=history,
    max_retries=advisor.max_retries,
)
```

Recreate the Advisor with the same `max_retries` value because retry policy
affects how its earlier observations are replayed. Do not share one
`AdviceHistory` between unrelated Project runs.

## How Plans become options

A Workflow may contain several target-reaching Plans, and a Plan may contain a
cycle. Plans that have the same executable next tool are shown as one root
option. Their identities remain available in `option.supporting_plans` and in
the advice snapshot.

For example, if two Plans begin with `Prepare`, the first advice shows
`Prepare` once. After `Prepare`, both branches can be shown. Once the observed
tool uniquely selects Plan A, later advice contains only the remainder of Plan
A. Plan B is parked as an earlier alternative and can return if Plan A is
exhausted; it is not repeatedly offered while Plan A is progressing normally.

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
backtracking, the Advisor uses the newest versions valid on the restored route,
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
8. `08_deviation_character/` — deviate into the wider ToolNetwork and compare
   how normative and homophilic Advisors order the same valid continuations.

Each example separates two concerns:

- `workflow.py` defines the artifacts, tools, and workflow. Running it saves
  `workflow.png` in the same folder. Example 08 also saves
  `tool_network.png` so its wider technical route is visible.
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

Equivalent Plan roots are grouped, valid candidates are ranked by the Advisor's
character, and only then is `max_options` applied. Stable network order resolves
remaining ties. With a very small limit, a valid option can therefore remain
hidden—for example, a cycle exit ordered after its repeat option. Use `None`
when every choice must remain visible.

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
- `input_artifacts`: available inputs as `(artifact name, version)` references;
  this matters when restoring a checkpoint that intentionally uses an older
  version.
- `continuations`: possible tools after this tool succeeds.
- `outcome`: `CONTINUE`, `TARGETS_READY`, `COMPLETE`, or `DEAD_END`.
- `has_more` and `options_truncated`: preview boundary markers.
- `scope`: `PROPOSED_PLAN`, `WORKFLOW_PLAN`, or `TOOL_NETWORK`.
- `transition`: `CONTINUE_CURRENT`, `REJOIN`, or `RESTORE_CHECKPOINT`.
- `supporting_plans`: compact tool-name signatures for the Plans represented
  by this option.

A missing artifact on a root option must be obtained before calling that tool.
A missing artifact on a nested continuation may be needed later, but only if
that route is followed. Artifacts created by earlier tools in the same preview
are not reported as missing from their consumers.

## Status, retry, backtracking, and completion

- `COMMAND`: choose one of the executable root tools. Normal progress,
  retries, backtracking, and deviation handling are all commands to the caller.
- `COMPLETE`: the project has completed.
- `BLOCKED`: every available route and retry has been exhausted.

When retry allowance remains after a failure, the failed tool's retry is
ordered first and unchecked sibling options follow it. Read `option.action` to
understand the instruction:

```python
for option in command.options:
    print(option.action, option.tool_name)
```

`RETRY` repeats a failed tool. `ALTERNATIVE` tries another available route.
After a branch and its retries are exhausted, options from the nearest earlier
decision point return as `ALTERNATIVE` commands. Their `input_artifacts`
identify the exact artifact versions to use on that route. Every option
includes the same success-based lookahead preview, and future failures are
handled only if they actually occur. The command status remains `COMMAND`
throughout.

The retry allowance is configurable:

```python
advisor = Advisor(project, max_retries=1)
```

`max_retries=1`, the default, permits one retry after the initial failed
attempt. `max_retries=0` permits no retry, so the Advisor proceeds directly to
an alternative or backtracks. Any positive `N` permits at most `N` retries
after the initial attempt. The allowance belongs to each option at one
decision visit: sibling options receive their own allowance, and returning to
the same decision during a later cycle begins a new visit with a fresh
allowance. Examples 05, 06, and 07 use the unchanged default of one retry.

If an observed tool was not part of the visible advice, `command.deviation`
records the tool, its location, and the options that had been shown. The
location is `PROPOSED_PLAN`, `WORKFLOW`, or `TOOL_NETWORK`. A deviation is not
automatically a failure; the returned command may offer ways to continue the
new direction, rejoin a Plan, or restore an earlier decision. If a deviating
tool fails, its retry and alternatives use the same option actions described
above.

A linear target completes automatically. If a cycle can create another target
candidate, `command.target_acceptance_required` is true. The observer may then
record `project.record_target_acceptance()` before asking again, or the caller
may choose a root continuation to create a new candidate.

This lightweight API intentionally avoids opaque option IDs. Tool definitions
have unique names, but the same tool can appear more than once when different
checkpoints would use different artifact versions. In that case,
`input_artifacts` distinguishes the commands. Execution is sequential, and
observations must arrive once and in order.

## Advisor character

Character changes the order of valid options; it does not change feasibility,
retry limits, or exhausted routes. Three presets cover the common cases:

```python
from artifactflow import BALANCED, HOMOPHILIC, NORMATIVE

normative = Advisor(project, character=NORMATIVE)
balanced = Advisor(project, character=BALANCED)
homophilic = Advisor(project, character=HOMOPHILIC)
```

- `NORMATIVE` prefers proposed Plans, then other Workflow Plans, then the wider
  ToolNetwork.
- `HOMOPHILIC` prefers continuing from the LLM's observed direction, then
  rejoining, then restoring an earlier checkpoint.
- `BALANCED` gives equal importance to those preferences.

A continuous blend is also available:

```python
from artifactflow import AdvisorCharacter

character = AdvisorCharacter(normativity=0.7)
advisor = Advisor(project, character=character)
```

`normativity` ranges from `0.0` to `1.0`; homophily is automatically
`1 - normativity`. A value of `0.5` balances both costs at every decision. It
does not randomly choose normative behavior half the time. When character
costs tie, fewer missing artifacts, fewer remaining tools, and stable network
order provide deterministic tie-breakers.
