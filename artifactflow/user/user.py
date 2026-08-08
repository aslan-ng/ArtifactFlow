"""External contributions to a project."""

from __future__ import annotations

from artifactflow.project.log import ArtifactVersion, FileReference
from artifactflow.project.project import Project


class User:
    """
    Record artifacts and decisions supplied from outside the workflow.

    This class intentionally does not decide where artifacts come from or
    whether targets have converged. A human, an LLM, historical data, or an
    example-specific policy can make those decisions and call these methods.
    """

    def __init__(self, project: Project) -> None:
        self.project = project

    def provide(
        self,
        artifact_name: str,
        *,
        value: object | None = None,
        file: FileReference | None = None,
    ) -> ArtifactVersion:
        """Record one external artifact, including its value or file."""
        return self.project.record_artifact_available(
            artifact_name,
            value=value,
            file=file,
        )

    def accept_targets(self) -> None:
        """Accept the target artifacts currently presented for review."""
        self.project.record_target_acceptance()
