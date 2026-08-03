from artifactflow.tool.tool import Tool
from artifactflow.artifact.examples import artifact_2, artifact_4, artifact_5


tool = Tool(
    name="Tool 3",
    inputs=[artifact_4],
    outputs=[artifact_2, artifact_5],
)