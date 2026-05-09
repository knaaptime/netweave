"""OSM network processing: travel-time weights and formatting."""


import pandas as pd

from netweave._logging import status
from netweave.types import METERS_PER_MILE, OSMNetwork


def create_osm_network(
    osm_network: OSMNetwork,
    walk_speed_mph: float = 3.0,
) -> OSMNetwork:
    """Create an OSM pedestrian network with travel-time weights.

    Parameters
    ----------
    osm_network : OSMNetwork
        Raw OSM network from osmnx.
    walk_speed_mph : float, optional
        Walking speed in miles per hour (default 3.0).

    Returns
    -------
    OSMNetwork
        Network with 'weight' column in minutes.
    """
    edges = osm_network.edges.copy()
    nodes = osm_network.nodes.copy()

    # Ensure length column exists
    if "length" not in edges.columns:
        raise ValueError("OSM edges must have a 'length' column (meters)")

    # Compute travel time in minutes
    # weight = (distance in miles) / (speed in mph) * 60 minutes/hour
    edges["weight"] = (edges["length"] / METERS_PER_MILE) / walk_speed_mph * 60.0

    # Ensure from/to columns exist
    if "u" in edges.columns and "v" in edges.columns:
        edges = edges.rename(columns={"u": "from", "v": "to"})

    status(f"OSM network weighted at {walk_speed_mph} mph")
    return OSMNetwork(edges=edges, nodes=nodes)
