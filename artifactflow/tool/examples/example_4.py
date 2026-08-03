from artifactflow.tool.tool import Tool
from artifactflow.artifact.examples import artifact_2, artifact_5


tool = Tool(
    name="Tool 4",
    inputs=[artifact_2],
    outputs=[artifact_5],
)