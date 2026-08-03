import networkx as nx
import matplotlib.pyplot as plt


class Graphics:
    G: nx.DiGraph

    def show(self):
        if not self.G:
            raise ValueError("The tool network is empty.")

        positions = nx.spring_layout(
            self.G,
            seed=42,
        )

        tool_nodes = [
            node
            for node, data in self.G.nodes(data=True)
            if data["type"] == "tool"
        ]

        artifact_nodes = [
            node
            for node, data in self.G.nodes(data=True)
            if data["type"] == "artifact"
        ]

        _, ax = plt.subplots(figsize=(10, 7))

        nx.draw_networkx_nodes(
            self.G,
            positions,
            nodelist=tool_nodes,
            node_color="tab:blue",
            node_shape="o",
            node_size=1800,
            ax=ax,
        )

        nx.draw_networkx_nodes(
            self.G,
            positions,
            nodelist=artifact_nodes,
            node_color="tab:orange",
            node_shape="s",
            node_size=1400,
            ax=ax,
        )

        node_sizes = [
            1800 if self.G.nodes[node]["type"] == "tool" else 1400
            for node in self.G.nodes
        ]

        nx.draw_networkx_edges(
            self.G,
            positions,
            node_size=node_sizes,
            arrows=True,
            arrowstyle="-|>",
            arrowsize=28,
            width=1.5,
            edge_color="gray",
            min_source_margin=15,
            min_target_margin=22,
            connectionstyle="arc3,rad=0.03",
            ax=ax,
        )

        nx.draw_networkx_labels(
            self.G,
            positions,
            font_color="white",
            font_size=9,
            ax=ax,
        )

        ax.set_axis_off()
        plt.tight_layout()
        plt.show()