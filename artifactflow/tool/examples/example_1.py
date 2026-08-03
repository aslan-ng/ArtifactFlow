from artifactflow.tool.tool import Tool
from artifactflow.artifact.examples import artifact_1, artifact_2


tool = Tool(
    name="Tool 1",
    inputs=[artifact_1],
    outputs=[artifact_2],
)