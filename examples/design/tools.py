import artifactflow as af


cad_file = af.Artifact("CAD File")
fea_results = af.Artifact("FEA Results")
fluid_results = af.Artifact("Fluid Results")
drag_results = af.Artifact("Drag Results")


tool_1 = af.Tool(
    name="Structural Simulation",
    inputs=[cad_file],
    outputs=[fea_results],
)

tool_2 = af.Tool(
    name="Fluid Simulation",
    inputs=[cad_file],
    outputs=[fluid_results],
)

tool_3 = af.Tool(
    name="Drag Analysis",
    inputs=[cad_file, fluid_results],
    outputs=[drag_results],
)

tool_4 = af.Tool(
    name="CAD Update",
    inputs=[fea_results, drag_results],
    outputs=[cad_file],
)

tools = [tool_1, tool_2, tool_3, tool_4]

tool_network = af.ToolNetwork()
for tool in tools:
    tool_network.add_tool(tool)


if __name__ == "__main__":
    tool_network.show()