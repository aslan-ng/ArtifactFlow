import networkx as nx

from artifactflow.utils.qap.qap import QAPStudy


workflow_a = nx.DiGraph()
workflow_b = nx.DiGraph()

nodes = {
    "requirements": "artifact",
    "CAD": "tool",
    "geometry": "artifact",
    "simulation": "tool",
    "results": "artifact",
    "review": "tool",
    "report": "artifact",
}

for node, node_type in nodes.items():
    workflow_a.add_node(node, node_type=node_type)
    workflow_b.add_node(node, node_type=node_type)


workflow_a.add_edges_from([
    ("requirements", "CAD"),
    ("CAD", "geometry"),
    ("geometry", "simulation"),
    ("simulation", "results"),
    ("results", "review"),
    ("review", "report"),
])

workflow_b.add_edges_from([
    ("requirements", "CAD"),
    ("CAD", "geometry"),
    ("geometry", "simulation"),
    ("simulation", "results"),
    ("results", "review"),

    # Different feedback structure
    ("review", "CAD"),
    ("review", "report"),
])


study = QAPStudy(
    networks={
        "Workflow A": workflow_a,
        "Workflow B": workflow_b,
    },
    node_type_attr="node_type",
    permutations=10_000,
    alternative="two-sided",
    random_state=42,
)

comparison = study.compare(
    "Workflow A",
    "Workflow B",
)

comparison.print_summary()
