from __future__ import annotations


from artifactflow.tool import Tool
from artifactflow.tool.compatibility.score_equation import io_match_score_equation


def tools_compatibility(
    previous_tools: list[Tool],
    next_tools: list[Tool],
    missing_input_penalty_ratio: float | int = 1.0,
) -> float:
    if missing_input_penalty_ratio < 0:
        raise ValueError(
            "missing_input_penalty_ratio cannot be negative."
        )

    output_names = {
        output.name
        for tool in previous_tools
        for output in tool.outputs
    }

    input_names = {
        input_.name
        for tool in next_tools
        for input_ in tool.inputs
    }

    matches = len(input_names & output_names)
    missing_inputs = len(input_names - output_names)

    return io_match_score_equation(
        matches=matches,
        missing_inputs=missing_inputs,
        missing_input_penalty_ratio=missing_input_penalty_ratio,
    )


def tool_readiness(
    previous_tools: list[Tool],
    candidate_tool: Tool,
    missing_input_penalty_ratio: float | int = 1.0,
) -> float:
    return tools_compatibility(
        previous_tools=previous_tools,
        next_tools=[candidate_tool],
        missing_input_penalty_ratio=missing_input_penalty_ratio,
    )


if __name__ == "__main__":

    from artifactflow.tool.examples import tool_1, tool_2, tool_3

    missing_input_penalty_ratio = 1.0

    def show(previous_tools, candidate_tool):
        score = tool_readiness(
            previous_tools=previous_tools,
            candidate_tool=candidate_tool,
            missing_input_penalty_ratio=missing_input_penalty_ratio,
        )
        print(f"Score for candidate tool '{candidate_tool.name}' with previous tools {[tool.name for tool in previous_tools]}: {score}")

    previous_tools = [tool_1, tool_2]
    candidate_tool = tool_3
    show(previous_tools, candidate_tool)

    previous_tools = [tool_1, tool_3]
    candidate_tool = tool_2
    show(previous_tools, candidate_tool)

    previous_tools = [tool_1]
    candidate_tool = tool_2
    show(previous_tools, candidate_tool)

    previous_tools = [tool_3]
    candidate_tool = tool_2
    show(previous_tools, candidate_tool)

    previous_tools = [tool_2, tool_3]
    candidate_tool = tool_1
    show(previous_tools, candidate_tool)

    