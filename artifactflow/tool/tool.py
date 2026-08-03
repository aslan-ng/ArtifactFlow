from __future__ import annotations

from artifactflow.artifact.artifact import Artifact


class Tool:

    def __init__(
        self,
        name,
        inputs: list[Artifact] | None = None,
        outputs: list[Artifact] | None = None,
        ):
        self.name = name
        
        self.inputs = inputs if inputs is not None else []
        self.outputs = outputs if outputs is not None else []

    def __str__(self) -> str:
        return self.name


if __name__ == "__main__":
    tool = Tool(
        name="CAD",
        inputs=[Artifact("STL")],
        outputs=[Artifact("GCODE")],
    )