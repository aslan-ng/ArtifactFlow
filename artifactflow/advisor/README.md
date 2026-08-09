# Understanding Advisor responses

`Advisor.advise()` returns one `AdvisorCommand`. The command answers:

1. Is there work to do, is the Project complete, or is it blocked?
2. If there is work to do, which tools can be called next?
3. What artifacts does each option need?
4. What may follow each option within the configured lookahead window?

The Advisor does not execute tools. A caller chooses one root option, obtains
its missing artifacts, calls the tool, lets an observer record the result, and
asks the Advisor again.

```python
command = advisor.advise()

if command.status == "COMMAND":
    option = command.options[0]
    print("Call:", option.tool_name)
    print("Provide first:", option.missing_artifacts)
elif command.status == "COMPLETE":
    print("Project completed:", command.target_artifacts)
elif command.status == "BLOCKED":
    print("No option remains.")
```

## The three command statuses

| Status | Meaning | What the caller should do |
| --- | --- | --- |
| `COMMAND` | At least one next tool is available, or a target candidate can be accepted. | Choose one root option, or accept the targets when requested. |
| `COMPLETE` | The Project's target artifacts are complete. | Stop. |
| `BLOCKED` | No valid tool option or allowed retry remains. | Stop or change something outside the current advising policy. |

Normal progress, retries, alternatives, backtracking, and responses to an LLM
deviation all use `status="COMMAND"`. There is no separate recovery response.

## Reading a `COMMAND`

The most important field is `command.options`:

```python
for option in command.options:
    print(option.tool_name)
```

Every item directly inside `command.options` is executable now. Multiple root
options are alternatives: choose one of them. Options nested inside
`option.continuations` are previews, not commands to execute yet.

For example, a lookahead response may conceptually look like this:

```python
AdvisorCommand(
    status="COMMAND",
    options=(
        ToolOption(
            tool_name="Tool 1",
            missing_artifacts=(),
            continuations=(
                ToolOption(
                    tool_name="Tool 2",
                    missing_artifacts=("Artifact 3",),
                    continuations=(
                        ToolOption(tool_name="Tool 3"),
                    ),
                ),
            ),
        ),
    ),
)
```

This means:

- `Tool 1` can be called now.
- If `Tool 1` succeeds, `Tool 2` may follow.
- That route will need `Artifact 3` before `Tool 2` runs.
- If `Tool 2` succeeds, `Tool 3` may follow.

Bootstrap requirements are not returned as one global list. They appear in
`missing_artifacts` on the root or preview option that first needs them. A
missing artifact on a preview is conditional: it matters only if that route is
eventually followed.

## `ToolOption` fields

| Field | Meaning |
| --- | --- |
| `tool_name` | The tool to call. Tool names are unique within a ToolNetwork. |
| `missing_artifacts` | Inputs that are not available in this option's state. Obtain them before calling the tool. |
| `input_artifacts` | Available inputs as exact `(artifact name, version)` bindings. Use these versions when the option restores an older checkpoint. |
| `action` | `RUN`, `RETRY`, or `ALTERNATIVE`. All three are executable tool options. |
| `continuations` | Conditional next options if this tool succeeds. These are previews only. |
| `outcome` | What success of this option is expected to mean within the preview. |
| `has_more` | `True` when more steps exist beyond the lookahead depth. |
| `options_truncated` | `True` when `max_options` hid some continuation choices. |
| `scope` | Whether the option belongs to proposed Plans, another Workflow Plan, or only the wider ToolNetwork. |
| `transition` | Whether the option continues, rejoins, or restores a previous checkpoint. |
| `supporting_plans` | Compact tool-name signatures for the Plans represented by this option. Mostly useful for inspection and research. |

### Actions

| Action | Meaning |
| --- | --- |
| `RUN` | Run a normal next tool. |
| `RETRY` | Run the failed tool again. It is still an ordinary executable option. |
| `ALTERNATIVE` | Try another route or a restored earlier choice. |

`Advisor(max_retries=N)` allows up to `N` retries after the initial attempt for
each option at one decision visit. The default is `1`. A later visit through a
cycle receives a fresh allowance.

### Expected outcomes

`option.outcome` describes the hypothetical state after that option succeeds:

| Outcome | Meaning |
| --- | --- |
| `CONTINUE` | More tools remain. |
| `TARGETS_READY` | The targets would be ready, but a repeatable target cycle allows another candidate, so acceptance is required. |
| `COMPLETE` | The option would complete the Project automatically. |
| `DEAD_END` | No continuation would remain and the targets would not be ready. |

The outcome belongs to a success-assuming preview. If the tool actually fails,
the observer records that failure and the next `advise()` call recalculates the
available options.

### Scope and transition

Scope describes an option relative to the Advisor's previous proposal:

| Scope | Meaning |
| --- | --- |
| `PROPOSED_PLAN` | Supported by a Plan the Advisor previously proposed. |
| `WORKFLOW_PLAN` | Supported by another valid Plan inside the Workflow. |
| `TOOL_NETWORK` | Technically possible in the ToolNetwork but outside the Workflow's Plans. |

Transition describes an option relative to the LLM's observed direction:

| Transition | Meaning |
| --- | --- |
| `CONTINUE_CURRENT` | Continue from the current artifact state. |
| `REJOIN` | Move from the current direction back into a known Plan. |
| `RESTORE_CHECKPOINT` | Return to an earlier decision and use its artifact state. |

The Advisor's character changes the ordering of valid options. A normative
Advisor favors proposed Plans; a homophilic Advisor favors continuing the
LLM's observed direction. Character changes ordering, not validity.

## Exact artifact versions

The same tool may appear more than once when it can run from different
checkpoints:

```python
ToolOption(
    tool_name="Use draft",
    input_artifacts=(("Draft", 2),),
    transition="CONTINUE_CURRENT",
)

ToolOption(
    tool_name="Use draft",
    input_artifacts=(("Draft", 1),),
    transition="RESTORE_CHECKPOINT",
)
```

These are different commands even though their `tool_name` is the same. The
caller should use `input_artifacts` to select the intended artifact versions.
ArtifactFlow deliberately avoids opaque option IDs.

## Lookahead and truncation

`lookahead_depth` controls how many success-assuming tool levels are shown:

```python
advisor = Advisor(
    project,
    lookahead_depth=3,
    max_options=2,
)
```

- Depth `1` shows only executable root tools.
- Larger depths populate nested `continuations`.
- `max_options` limits alternatives after ranking.
- `command.options_truncated` means some executable root alternatives were
  hidden.
- `option.options_truncated` means some preview alternatives were hidden.
- `option.has_more` means the preview ended because of depth, not because the
  Plan ended.

Cycles are never expanded into every possible iteration count. They appear as
structural repeated possibilities only within the finite lookahead window.

## Target responses

### Automatic completion

A linear process normally ends with:

```python
AdvisorCommand(
    status="COMPLETE",
    options=(),
    target_artifacts=("Result",),
)
```

### A target cycle awaiting acceptance

If a cycle can produce another target candidate, the response remains a
command:

```python
AdvisorCommand(
    status="COMMAND",
    options=(...),
    target_artifacts=("Result",),
    target_acceptance_required=True,
)
```

The caller can either:

1. record target acceptance and ask again, which produces `COMPLETE`; or
2. choose one of the root options to produce another candidate.

### Blocked

When every option and its allowed retries have been exhausted:

```python
AdvisorCommand(
    status="BLOCKED",
    options=(),
)
```

## Deviation information

When the observed LLM action was not one of the options actually shown,
`command.deviation` contains explanatory context:

```python
DeviationContext(
    observed_tool="Improvised analysis",
    location="TOOL_NETWORK",
    proposed_options=("Approved analysis",),
)
```

The possible locations are `PROPOSED_PLAN`, `WORKFLOW`, and `TOOL_NETWORK`.
A deviation is not a separate status and is not automatically a failure. The
root options still contain every executable next choice: continue the new
direction, rejoin a Plan, or restore an earlier checkpoint, depending on what
is structurally possible.

## `AdvisorCommand` fields

| Field | Meaning |
| --- | --- |
| `status` | `COMMAND`, `COMPLETE`, or `BLOCKED`. |
| `options` | Executable root options when status is `COMMAND`. |
| `options_truncated` | Whether `max_options` hid root alternatives. |
| `target_artifacts` | Ready or completed target artifact names. Empty while targets are not ready. |
| `target_acceptance_required` | Whether a cyclic target candidate needs explicit acceptance. |
| `deviation` | Optional context about an observed action outside the visible advice. |
| `message` | A short human summary. Structured fields should control program behavior. |

## Minimal caller loop

```python
while True:
    command = advisor.advise()

    if command.status == "COMPLETE":
        break

    if command.status == "BLOCKED":
        break

    if command.target_acceptance_required:
        # Perform the domain-specific target check. If accepted:
        project.record_target_acceptance()
        continue

    option = command.options[0]

    for artifact_name in option.missing_artifacts:
        project.record_artifact_available(artifact_name)

    # The actual application calls option.tool_name here. Its observer then
    # records either success or failure before the loop asks again.
    project.record_tool_success(option.tool_name)
```

The examples in [`../../examples`](../../examples) show linear routes,
route choices, cycles, retries, backtracking, blocking, and deviation-aware
characters using the same response structure.
