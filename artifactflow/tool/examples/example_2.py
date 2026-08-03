from artifactflow.tool.tool import Tool
from artifactflow.artifact.examples import artifact_2, artifact_3, artifact_4


tool = Tool(
    name="Tool 2",
    inputs=[artifact_2, artifact_3],
    outputs=[artifact_4],
)