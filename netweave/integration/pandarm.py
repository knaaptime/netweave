"""Read a pedestrian network out of pandarm, and build the result back into it.

pandarm's constructor keeps only coordinates, impedances and geometry, so netweave
adds its node and edge labels and its metadata to the finished network. Those
additions, and the restriction of snapping to pedestrian nodes, do not survive
``from_hdf5`` or ``to_crs`` until pandarm learns to keep them. See
``docs/adr/0002-pandarm-network-is-the-only-network-type.md``.
"""

from typing import Any

import geopandas as gpd
import numpy as np
import pandarm
import pandas as pd
import shapely

from netweave.exceptions import NetworkIntegrationError
from netweave.transform.impedance import to_minutes

# pandarm stores costs as fixed-point integers, so non-finite values and very large ones
# overflow into costs near zero. A million minutes is about two years.
_MAX_MINUTES: float = 1e6

EDGE_LABELS: tuple[str, ...] = ("edge_type", "route_id", "direction_id")
NODE_LABELS: tuple[str, ...] = ("node_type", "stop_id", "route_id", "direction_id", "feed")


def _chosen_impedance(network: pandarm.Network, impedance: str | None) -> str:
    """Return the impedance to read, requiring a name when there is a choice."""
    names = list(network.impedance_names)
    if impedance is None:
        if len(names) != 1:
            raise ValueError(
                f"The pedestrian network has several impedances ({', '.join(names)}): "
                "name one with pedestrian_impedance"
            )
        return names[0]
    if impedance not in names:
        raise ValueError(
            f"The pedestrian network has no impedance '{impedance}': it has {', '.join(names)}"
        )
    return impedance


def pedestrian_tables(
    network: pandarm.Network,
    impedance: str | None,
    unit: str,
    walk_speed_mph: float,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Return a pedestrian network's nodes and directed walk edges, priced in minutes.

    Parameters
    ----------
    network : pandarm.Network
        The pedestrian network.
    impedance : str, optional
        The impedance to read. May be omitted when the network has only one.
    unit : {"meters", "minutes", "seconds"}
        The unit of that impedance.
    walk_speed_mph : float
        Walking speed, used only for distances.

    Returns
    -------
    tuple
        Nodes indexed by node ID, with ``x`` and ``y``; edges with one row per
        direction and at most one row between two nodes in each direction; and
        the name of the impedance read.
    """
    impedance = _chosen_impedance(network, impedance)
    nodes = pd.DataFrame(network.nodes_df[["x", "y"]]).astype(float)

    source = network.edges_df
    edges = pd.DataFrame(
        {
            "from": source["from"].to_numpy(),
            "to": source["to"].to_numpy(),
            "minutes": to_minutes(source[impedance].to_numpy(dtype=float), unit, walk_speed_mph),
        }
    )
    has_geometry = "geometry" in source.columns
    edges["geometry"] = source["geometry"].to_numpy() if has_geometry else None

    if network._twoway:
        reverse = edges.rename(columns={"from": "to", "to": "from"})[edges.columns]
        if has_geometry:
            reverse["geometry"] = shapely.reverse(reverse["geometry"].to_numpy())
        edges = pd.concat([edges, reverse], ignore_index=True)

    edges = (
        edges.sort_values("minutes", kind="stable")
        .drop_duplicates(["from", "to"])
        .sort_index()
        .reset_index(drop=True)
    )
    return nodes, edges, impedance


def _check_minutes(edges: pd.DataFrame) -> None:
    """Refuse costs that pandarm would silently misread."""
    minutes = edges["minutes"].to_numpy(dtype=float)
    unusable = ~np.isfinite(minutes) | (minutes < 0) | (minutes > _MAX_MINUTES)
    if unusable.any():
        kinds = sorted(set(edges.loc[unusable, "edge_type"]))
        raise NetworkIntegrationError(
            f"{int(unusable.sum())} {'/'.join(kinds)} edge(s) cost a number of minutes that is "
            f"missing, negative, or above {_MAX_MINUTES:,.0f}. Check pedestrian_unit and "
            "pedestrian_impedance."
        )


def build_network(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    crs: Any,
    metadata: dict[str, Any],
    pedestrian_nodes: int,
) -> pandarm.Network:
    """Build a pandarm network that carries netweave's labels and metadata.

    Parameters
    ----------
    nodes : pandas.DataFrame
        Nodes indexed by node ID, with the pedestrian nodes first.
    edges : pandas.DataFrame
        Directed edges priced in minutes.
    crs : object
        The coordinate reference system of the nodes and edges.
    metadata : dict
        Stored as ``network.metadata``.
    pedestrian_nodes : int
        The number of pedestrian nodes, to which snapping is restricted. A point
        that landed on a route-stop would make walkers pay the wait to reach it,
        and let trips begun there skip the wait.

    Returns
    -------
    pandarm.Network
    """
    _check_minutes(edges)
    network = pandarm.Network(
        nodes["x"],
        nodes["y"],
        edges["from"],
        edges["to"],
        edges[["minutes"]],
        twoway=False,
        edge_geom=gpd.GeoSeries(edges["geometry"], crs=crs),
        crs=crs,
    )
    for label in NODE_LABELS:
        network.nodes_df[label] = nodes[label].to_numpy()
    for label in EDGE_LABELS:
        network.edges_df[label] = edges[label].to_numpy()
    network.metadata = metadata
    network.kdtree = type(network.kdtree)(nodes[["x", "y"]].to_numpy()[:pedestrian_nodes])
    return network
