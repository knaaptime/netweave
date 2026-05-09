"""OSM network loading utilities."""


from typing import Optional

import osmnx as ox
import pandas as pd

from netweave._logging import status
from netweave.types import OSMNetwork


def load_network_from_bbox(
    bbox: tuple[float, float, float, float],
    network_type: str = "walk",
    simplify: bool = True,
    retain_all: bool = False,
) -> OSMNetwork:
    """Load an OSM pedestrian network from a bounding box.

    Parameters
    ----------
    bbox : tuple[float, float, float, float]
        Bounding box as (left, bottom, right, top) in unprojected
        latitude-longitude degrees (EPSG:4326), i.e.
        (min_lon, min_lat, max_lon, max_lat).
    network_type : str, optional
        Network type for osmnx (default 'walk').
    simplify : bool, optional
        If True, simplify the graph topology.
    retain_all : bool, optional
        If True, retain all nodes even if disconnected.

    Returns
    -------
    OSMNetwork
    """
    status(f"Downloading OSM network for bbox: {bbox}")
    G = ox.graph_from_bbox(
        bbox=bbox,
        network_type=network_type,
        simplify=simplify,
        retain_all=retain_all,
    )
    nodes, edges = ox.graph_to_gdfs(G)

    # Ensure integer index for nodes
    nodes = nodes.reset_index().rename(columns={"osmid": "node_id"})
    edges = edges.reset_index()

    status(f"OSM network: {len(nodes)} nodes, {len(edges)} edges")
    return OSMNetwork(edges=edges, nodes=nodes)


def load_network_from_polygon(
    polygon,
    network_type: str = "walk",
    simplify: bool = True,
    retain_all: bool = False,
) -> OSMNetwork:
    """Load an OSM pedestrian network from a polygon boundary.

    Parameters
    ----------
    polygon : shapely.geometry.Polygon or geopandas.GeoSeries
        Polygon boundary.
    network_type : str, optional
        Network type for osmnx (default 'walk').
    simplify : bool, optional
        If True, simplify the graph topology.
    retain_all : bool, optional
        If True, retain all nodes even if disconnected.

    Returns
    -------
    OSMNetwork
    """
    status("Downloading OSM network for polygon boundary")
    G = ox.graph_from_polygon(
        polygon=polygon,
        network_type=network_type,
        simplify=simplify,
        retain_all=retain_all,
    )
    nodes, edges = ox.graph_to_gdfs(G)

    nodes = nodes.reset_index().rename(columns={"osmid": "node_id"})
    edges = edges.reset_index()

    status(f"OSM network: {len(nodes)} nodes, {len(edges)} edges")
    return OSMNetwork(edges=edges, nodes=nodes)
