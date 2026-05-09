"""Pandarm bridge: convert IntegratedNetwork to pandarm.Network."""


import pandas as pd

from netweave._logging import status
from netweave.types import IntegratedNetwork


def to_pandarm(
    network: IntegratedNetwork,
    twoway: bool = False,
) -> "pandarm.Network":
    """Convert an IntegratedNetwork to a pandarm.Network.

    Parameters
    ----------
    network : IntegratedNetwork
        The integrated transit + pedestrian network.
    twoway : bool, optional
        If True, treat edges as undirected so that travel can occur in
        both directions on each edge. If False (default), edges are
        one-way only. The default is False because integrated networks
        already contain bidirectional walking and connector edges, and
        transit edges are directional (a bus route from A to B should
        not allow travel from B to A at the same cost). Set to True
        only for pure walking networks without transit.

    Returns
    -------
    pandarm.Network
    """
    import pandarm

    nodes = network.nodes.copy()
    edges = network.edges.copy()

    # Ensure x and y columns exist
    if "x" not in nodes.columns or "y" not in nodes.columns:
        raise ValueError("Nodes must have 'x' and 'y' columns")

    # Ensure from/to columns exist
    if "from" not in edges.columns or "to" not in edges.columns:
        raise ValueError("Edges must have 'from' and 'to' columns")

    # Ensure weight column exists
    if "weight" not in edges.columns:
        raise ValueError("Edges must have a 'weight' column")

    # Always remap node IDs to contiguous integers for pandarm compatibility.
    # This ensures consistent typing and avoids mixed string/int IDs from
    # different sources (GTFS stop_ids vs OSM osmids).
    nodes["original_node_id"] = nodes["node_id"]
    nodes["node_id"] = range(len(nodes))

    # Build mapping from original ID to new unique ID
    id_map = dict(zip(nodes["original_node_id"], nodes["node_id"]))

    # Map edge from/to to new integer IDs
    edges["from"] = edges["from"].map(id_map)
    edges["to"] = edges["to"].map(id_map)

    # Drop edges with missing node mappings (orphan edges)
    n_before = len(edges)
    edges = edges.dropna(subset=["from", "to"]).copy()
    if len(edges) < n_before:
        status(f"WARNING: Dropped {n_before - len(edges)} edges with missing node IDs")

    # Ensure from/to are int64 (not object/float from missing mappings)
    edges["from"] = edges["from"].astype("int64")
    edges["to"] = edges["to"].astype("int64")

    # Set node_id as index for pandarm
    nodes = nodes.set_index("node_id")

    edge_weights = edges[["weight"]].copy()

    # Pass geometry to pandarm if available
    edge_geom = None
    if "geometry" in edges.columns:
        edge_geom = edges["geometry"]

    status(f"Building pandarm.Network with {len(nodes)} nodes and {len(edges)} edges")

    return pandarm.Network(
        node_x=nodes["x"],
        node_y=nodes["y"],
        edge_from=edges["from"],
        edge_to=edges["to"],
        edge_weights=edge_weights,
        twoway=twoway,
        edge_geom=edge_geom,
    )


def format_for_pandarm(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.DataFrame, pd.Series | None]:
    """Format nodes and edges for pandarm.Network constructor.

    Parameters
    ----------
    nodes : pandas.DataFrame
        Nodes with 'node_id', 'x', 'y' columns.
    edges : pandas.DataFrame
        Edges with 'from', 'to', 'weight' columns. May also have
        a 'geometry' column of shapely LineStrings.

    Returns
    -------
    tuple
        (node_x, node_y, edge_from, edge_to, edge_weights, edge_geom)
        edge_geom is None if no geometry column is present.
    """
    nodes = nodes.copy()
    edges = edges.copy()

    # Always remap node IDs to contiguous integers for pandarm compatibility.
    # This ensures consistent typing and avoids mixed string/int IDs from
    # different sources (GTFS stop_ids vs OSM osmids).
    nodes["original_node_id"] = nodes["node_id"]
    nodes["node_id"] = range(len(nodes))
    id_map = dict(zip(nodes["original_node_id"], nodes["node_id"]))

    edges["from"] = edges["from"].map(id_map).astype("int64")
    edges["to"] = edges["to"].map(id_map).astype("int64")

    if "node_id" in nodes.columns:
        nodes = nodes.set_index("node_id")

    if "x" not in nodes.columns or "y" not in nodes.columns:
        raise ValueError("Nodes must have 'x' and 'y' columns")
    if "from" not in edges.columns or "to" not in edges.columns:
        raise ValueError("Edges must have 'from' and 'to' columns")
    if "weight" not in edges.columns:
        raise ValueError("Edges must have a 'weight' column")

    node_x = nodes["x"]
    node_y = nodes["y"]
    edge_from = edges["from"]
    edge_to = edges["to"]
    edge_weights = edges[["weight"]].copy()

    edge_geom = edges["geometry"] if "geometry" in edges.columns else None

    return node_x, node_y, edge_from, edge_to, edge_weights, edge_geom
