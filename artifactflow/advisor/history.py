"""Immutable records of advice shown at each observed project state."""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import TypeAlias

from artifactflow.plan.plan import Plan


PlanSignature: TypeAlias = tuple[str, ...]
ArtifactBinding: TypeAlias = tuple[str, int]
SupportingPlanSignatures: TypeAlias = tuple[
    tuple[str, tuple[PlanSignature, ...]],
    ...,
]
_ANY_CONFIGURATION: Hashable = object()


@dataclass(frozen=True, slots=True)
class AdvisedOption:
    """The concrete tool state represented by one visible root option."""

    tool_name: str
    input_artifacts: tuple[ArtifactBinding, ...] = ()
    supporting_plan_signatures: tuple[PlanSignature, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.tool_name, str):
            raise TypeError("tool_name must be a string.")
        _validate_artifact_bindings(self.input_artifacts)
        _validate_plan_signatures(self.supporting_plan_signatures)
        object.__setattr__(
            self,
            "supporting_plan_signatures",
            _unique_signatures(self.supporting_plan_signatures),
        )


@dataclass(frozen=True, slots=True)
class AdviceSnapshot:
    """Advice issued after a particular number of project events.

    ``event_position`` is the number of execution events already observed
    when the advice was issued. Plan objects are represented by their ordered
    tool names so that a snapshot stays small and immutable.
    """

    event_position: int
    configuration: Hashable
    options: tuple[AdvisedOption, ...] = ()

    def __post_init__(self) -> None:
        _validate_event_position(self.event_position)
        _validate_configuration(self.configuration)
        if not isinstance(self.options, tuple) or not all(
            isinstance(option, AdvisedOption)
            for option in self.options
        ):
            raise TypeError("options must be a tuple of AdvisedOption objects.")
        identities = tuple(
            (option.tool_name, option.input_artifacts)
            for option in self.options
        )
        if len(identities) != len(set(identities)):
            raise ValueError("Advice options must have unique tool/input states.")

    @property
    def visible_root_tools(self) -> tuple[str, ...]:
        """Return visible tool names, including version-specific repeats."""
        return tuple(option.tool_name for option in self.options)

    @property
    def supporting_plan_signatures(self) -> SupportingPlanSignatures:
        """Return the legacy positional view of option Plan signatures."""
        return tuple(
            (option.tool_name, option.supporting_plan_signatures)
            for option in self.options
        )

    @classmethod
    def create(
        cls,
        *,
        event_position: int,
        configuration: Hashable,
        visible_root_tools: Iterable[str] = (),
        supporting_plans: Mapping[str, Iterable[Plan]] | None = None,
        options: Iterable[AdvisedOption] | None = None,
    ) -> AdviceSnapshot:
        """Create a validated snapshot from the Plans behind each option."""
        _validate_event_position(event_position)
        _validate_configuration(configuration)

        if options is not None:
            legacy_tools = tuple(visible_root_tools)
            if legacy_tools or supporting_plans is not None:
                raise ValueError(
                    "options cannot be combined with visible_root_tools or "
                    "supporting_plans."
                )
            advised_options = tuple(options)
            return cls(
                event_position=event_position,
                configuration=configuration,
                options=advised_options,
            )

        root_tools = _unique_names(
            visible_root_tools,
            name="visible_root_tools",
        )
        if supporting_plans is not None and not isinstance(
            supporting_plans,
            Mapping,
        ):
            raise TypeError("supporting_plans must be a mapping or None.")
        plans_by_tool = supporting_plans or {}
        _unique_names(
            plans_by_tool,
            name="supporting_plans keys",
        )
        unknown_tools = set(plans_by_tool) - set(root_tools)
        if unknown_tools:
            raise ValueError(
                "supporting_plans contains tools that are not visible root "
                f"options: {sorted(unknown_tools)}"
            )

        signatures: list[tuple[str, tuple[PlanSignature, ...]]] = []
        for tool_name in root_tools:
            plans = tuple(plans_by_tool.get(tool_name, ()))
            if not all(isinstance(plan, Plan) for plan in plans):
                raise TypeError(
                    "supporting_plans must contain Plan objects."
                )
            plan_signatures = _unique_signatures(
                tuple(tuple(plan.tool_names) for plan in plans)
            )
            signatures.append((tool_name, plan_signatures))

        return cls(
            event_position=event_position,
            configuration=configuration,
            options=tuple(
                AdvisedOption(
                    tool_name=tool_name,
                    supporting_plan_signatures=plan_signatures,
                )
                for tool_name, plan_signatures in signatures
            ),
        )

    def plans_for(
        self,
        tool_name: str,
        input_artifacts: tuple[ArtifactBinding, ...] | None = None,
    ) -> tuple[PlanSignature, ...]:
        """Return Plans for a tool, optionally at one exact input state.

        Omitting ``input_artifacts`` preserves the original tool-name lookup
        and combines signatures across every visible state of that tool.
        """
        if not isinstance(tool_name, str):
            raise TypeError("tool_name must be a string.")
        if input_artifacts is not None:
            _validate_artifact_bindings(input_artifacts)
        signatures = (
            signature
            for option in self.options
            if option.tool_name == tool_name
            and (
                input_artifacts is None
                or option.input_artifacts == input_artifacts
            )
            for signature in option.supporting_plan_signatures
        )
        return tuple(dict.fromkeys(signatures))

    def option_for(
        self,
        tool_name: str,
        input_artifacts: tuple[ArtifactBinding, ...] = (),
    ) -> AdvisedOption | None:
        """Return one visible option by its exact tool and input state."""
        if not isinstance(tool_name, str):
            raise TypeError("tool_name must be a string.")
        _validate_artifact_bindings(input_artifacts)
        return next(
            (
                option
                for option in self.options
                if option.tool_name == tool_name
                and option.input_artifacts == input_artifacts
            ),
            None,
        )


class AdviceHistory:
    """Store one deterministic advice snapshot per state and configuration.

    Calling ``record`` again without a new project event and with the same
    configuration returns the original object. Different advice for that
    same key is rejected because it would make later deviation analysis
    ambiguous.
    """

    def __init__(self) -> None:
        self._snapshots: list[AdviceSnapshot] = []
        self._issuances: list[AdviceSnapshot] = []
        self._by_key: dict[tuple[int, Hashable], AdviceSnapshot] = {}

    @property
    def snapshots(self) -> tuple[AdviceSnapshot, ...]:
        """Return every distinct snapshot in recording order."""
        return tuple(self._snapshots)

    def __len__(self) -> int:
        return len(self._snapshots)

    def __iter__(self) -> Iterator[AdviceSnapshot]:
        return iter(self.snapshots)

    def record(
        self,
        *,
        event_position: int,
        configuration: Hashable,
        visible_root_tools: Iterable[str] = (),
        supporting_plans: Mapping[str, Iterable[Plan]] | None = None,
        options: Iterable[AdvisedOption] | None = None,
    ) -> AdviceSnapshot:
        """Record advice, or reuse the snapshot for an unchanged state.

        ``options`` records exact tool/input-version identities. The older
        ``visible_root_tools`` and ``supporting_plans`` arguments remain for
        callers that only need tool-name identity.
        """
        snapshot = AdviceSnapshot.create(
            event_position=event_position,
            configuration=configuration,
            visible_root_tools=visible_root_tools,
            supporting_plans=supporting_plans,
            options=options,
        )
        key = (event_position, configuration)
        previous = self._by_key.get(key)
        if previous is not None:
            if previous != snapshot:
                raise ValueError(
                    "Different advice is already recorded for this event "
                    "position and configuration."
                )
            if not self._issuances or self._issuances[-1] is not previous:
                self._issuances.append(previous)
            return previous

        self._by_key[key] = snapshot
        self._snapshots.append(snapshot)
        self._issuances.append(snapshot)
        return snapshot

    def get(
        self,
        event_position: int,
        configuration: Hashable,
    ) -> AdviceSnapshot | None:
        """Return the snapshot for an exact state/configuration pair."""
        _validate_event_position(event_position)
        _validate_configuration(configuration)
        return self._by_key.get((event_position, configuration))

    def latest(
        self,
        configuration: Hashable = _ANY_CONFIGURATION,
    ) -> AdviceSnapshot | None:
        """Return the most recently recorded matching snapshot."""
        if configuration is not _ANY_CONFIGURATION:
            _validate_configuration(configuration)
        return next(
            (
                snapshot
                for snapshot in reversed(self._issuances)
                if configuration is _ANY_CONFIGURATION
                or snapshot.configuration == configuration
            ),
            None,
        )

    def latest_before(
        self,
        event_position: int,
        configuration: Hashable = _ANY_CONFIGURATION,
    ) -> AdviceSnapshot | None:
        """Return the latest advice issued before an event position.

        The comparison is strict. For example, advice at position two was
        issued after two events and is the advice preceding position three.
        """
        _validate_event_position(event_position)
        if configuration is not _ANY_CONFIGURATION:
            _validate_configuration(configuration)

        return next(
            (
                snapshot
                for snapshot in reversed(self._issuances)
                if snapshot.event_position < event_position
                and (
                    configuration is _ANY_CONFIGURATION
                    or snapshot.configuration == configuration
                )
            ),
            None,
        )


def _validate_event_position(event_position: int) -> None:
    if isinstance(event_position, bool) or not isinstance(
        event_position,
        int,
    ):
        raise TypeError("event_position must be an integer.")
    if event_position < 0:
        raise ValueError("event_position cannot be negative.")


def _validate_configuration(configuration: Hashable) -> None:
    try:
        hash(configuration)
    except TypeError as error:
        raise TypeError("configuration must be hashable.") from error


def _unique_names(
    names: Iterable[str],
    *,
    name: str,
) -> tuple[str, ...]:
    values = tuple(names)
    if not all(isinstance(value, str) for value in values):
        raise TypeError(f"{name} must contain strings.")
    if len(values) != len(set(values)):
        raise ValueError(f"{name} cannot contain duplicates.")
    return values


def _unique_signatures(
    signatures: Iterable[PlanSignature],
) -> tuple[PlanSignature, ...]:
    return tuple(dict.fromkeys(signatures))


def _validate_artifact_bindings(
    bindings: tuple[ArtifactBinding, ...],
) -> None:
    if not isinstance(bindings, tuple):
        raise TypeError("input_artifacts must be a tuple.")
    for binding in bindings:
        if (
            not isinstance(binding, tuple)
            or len(binding) != 2
            or not isinstance(binding[0], str)
            or isinstance(binding[1], bool)
            or not isinstance(binding[1], int)
        ):
            raise TypeError(
                "Artifact bindings must be (name, positive version) tuples."
            )
        if binding[1] < 1:
            raise ValueError("Artifact versions must be positive integers.")
    if len(bindings) != len(set(bindings)):
        raise ValueError("input_artifacts cannot contain duplicates.")


def _validate_plan_signatures(
    signatures: tuple[PlanSignature, ...],
) -> None:
    if not isinstance(signatures, tuple):
        raise TypeError("supporting_plan_signatures must be a tuple.")
    for signature in signatures:
        if not isinstance(signature, tuple) or not all(
            isinstance(name, str) for name in signature
        ):
            raise TypeError("A Plan signature must be a tuple of tool names.")


__all__ = [
    "AdvisedOption",
    "AdviceHistory",
    "AdviceSnapshot",
    "ArtifactBinding",
]
