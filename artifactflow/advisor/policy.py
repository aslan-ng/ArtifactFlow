"""Small, explainable policies for ordering valid advice candidates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import math


class CandidateScope(IntEnum):
    """How far a candidate moves from the Advisor's previous proposal."""

    PROPOSED_PLAN = 0
    WORKFLOW_PLAN = 1
    TOOL_NETWORK = 2


class CandidateTransition(IntEnum):
    """How far a candidate moves from the agent's current direction."""

    CONTINUE_CURRENT = 0
    REJOIN = 1
    RESTORE_CHECKPOINT = 2


@dataclass(frozen=True, slots=True)
class AdvisorCharacter:
    """Balance adherence to advice against following the agent's direction.

    ``normativity=1`` ranks only by candidate scope. ``normativity=0``
    ranks only by the transition from the current direction. Intermediate
    values blend the two costs at every decision; they are not probabilities.
    """

    normativity: float = 1.0

    def __post_init__(self) -> None:
        value = self.normativity
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("normativity must be a number between 0 and 1.")

        normalized = float(value)
        if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
            raise ValueError("normativity must be between 0 and 1.")
        object.__setattr__(self, "normativity", normalized)

    @property
    def homophily(self) -> float:
        """Return the complementary preference for the current direction."""
        return 1.0 - self.normativity

    def cost(
        self,
        scope: CandidateScope,
        transition: CandidateTransition,
    ) -> float:
        """Return the blended character cost; lower values rank first."""
        _check_candidate_kinds(scope, transition)
        return (
            self.normativity * scope.value
            + self.homophily * transition.value
        )

    def rank(
        self,
        scope: CandidateScope,
        transition: CandidateTransition,
        *,
        missing_artifacts: int = 0,
        remaining_tools: int = 0,
        stable_order: int = 0,
    ) -> tuple[float, int, int, int]:
        """Return a deterministic sorting key for one valid candidate.

        Feasibility and recovery exhaustion must be checked before ranking.
        The small integer fields are deliberately only tie-breakers so the
        character remains easy to understand and extend later.
        """
        for name, value in (
            ("missing_artifacts", missing_artifacts),
            ("remaining_tools", remaining_tools),
            ("stable_order", stable_order),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer.")
            if value < 0:
                raise ValueError(f"{name} cannot be negative.")

        return (
            self.cost(scope, transition),
            missing_artifacts,
            remaining_tools,
            stable_order,
        )


def _check_candidate_kinds(
    scope: CandidateScope,
    transition: CandidateTransition,
) -> None:
    if not isinstance(scope, CandidateScope):
        raise TypeError("scope must be a CandidateScope.")
    if not isinstance(transition, CandidateTransition):
        raise TypeError("transition must be a CandidateTransition.")


NORMATIVE = AdvisorCharacter(normativity=1.0)
BALANCED = AdvisorCharacter(normativity=0.5)
HOMOPHILIC = AdvisorCharacter(normativity=0.0)


__all__ = [
    "AdvisorCharacter",
    "BALANCED",
    "CandidateScope",
    "CandidateTransition",
    "HOMOPHILIC",
    "NORMATIVE",
]
