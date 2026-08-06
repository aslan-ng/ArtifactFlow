from artifactflow.workflow import Workflow
from artifactflow.tool.examples import tool_1, tool_4


workflow = Workflow()
workflow.add_tool(tool_1)
workflow.add_tool(tool_4)


if __name__ == "__main__":
    workflow.show()