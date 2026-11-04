"""Network integration logic: connector edges and headway impedance."""


from typing import Optional, Union

import numpy as np
import pandas as pd
import pandarm
from shapely.geometry import LineString
from sklearn.neighbors import BallTree

from netweave._logging import _log, status
from netweave.exceptions import EmptyNetworkError, NetworkIntegrationError
from netweave.types import (
    DEFAULT_WALK_SPEED_MPH,
    IntegratedNetwork,
    METERS_PER_MILE,
    OSMNetwork,
    TransitNetwork,
)

# Earth radius in meters (WGS-84 mean radius)
_EARTH_RADIUS_M: float = 6_371_008.8


def _pandarm_to_osm_network(
    net: pandarm.Network,
    walk_speed_mph: float = DEFAULT_WALK_SPEED_MPH,
    weight_unit: str = "auto",
) -> OSMNetwork:
    """Convert a pandarm.Network to an OSMNetwork for integration.

    Extracts nodes and edges from a pandarm.Network and normalizes
    column names to match netweave conventions.

    If the edge weights appear to be in meters (the default for pandarm
    networks created from OSM data), they are converted to walking time
    in minutes to match netweave's convention.

    Parameters
    ----------
    net : pandarm.Network
        An existing pandarm.Network.
    walk_speed_mph : float, optional
        Walking speed in mph used to convert meter-based weights to
        minutes (default 3.0).
    weight_unit : str, optional
        Unit of the edge weights in the pandarm.Network. One of:

        - ``"auto"`` (default): Detect units automatically. If the
          impedance name is ``"length"`` or the mean weight exceeds 10,
          weights are assumed to be in meters and converted to minutes.
        - ``"meters"``: Always convert from meters to minutes.
        - ``"minutes"``: Never convert (weights are already in minutes).
        - ``"seconds"``: Convert from seconds to minutes.

    Returns
    -------
    OSMNetwork
    """
    nodes = net.nodes_df.copy()
    edges = net.edges_df.copy()

    # Ensure node_id is a column (pandarm uses index for node IDs)
    # The index may be named (e.g. "osmid" from osmnx) or unnamed,
    # so we handle both cases robustly.
    if "node_id" not in nodes.columns:
        index_name = nodes.index.name if nodes.index.name else "index"
        nodes = nodes.reset_index().rename(columns={index_name: "node_id"})

    # Ensure x and y columns exist
    if "x" not in nodes.columns or "y" not in nodes.columns:
        raise NetworkIntegrationError(
            "pandarm.Network nodes must have 'x' and 'y' columns"
        )

    # Ensure from and to columns exist in edges
    if "from" not in edges.columns or "to" not in edges.columns:
        raise NetworkIntegrationError(
            "pandarm.Network edges must have 'from' and 'to' columns"
        )

    # Ensure weight column exists
    if "weight" not in edges.columns:
        if hasattr(net, "impedance_names") and net.impedance_names:
            weight_col = net.impedance_names[0]
            edges = edges.rename(columns={weight_col: "weight"})
        else:
            raise NetworkIntegrationError(
                "pandarm.Network edges must have a 'weight' column or impedance_names"
            )

    # Convert weights to minutes based on the specified unit.
    # pandarm networks created from OSM data use 'length' (meters) as the
    # default impedance, but netweave conventions require weights in minutes.
    weight_unit = weight_unit.lower()
    if weight_unit not in ("auto", "meters", "minutes", "seconds"):
        raise ValueError(
            f"weight_unit must be 'auto', 'meters', 'minutes', or 'seconds', "
            f"got '{weight_unit}'"
        )

    if weight_unit == "minutes":
        # Weights are already in minutes — no conversion needed.
        pass
    elif weight_unit == "seconds":
        # Convert seconds to minutes.
        edges["weight"] = edges["weight"] / 60.0
    elif weight_unit == "meters":
        # Always convert meters to walking time in minutes.
        edges["weight"] = (edges["weight"] / METERS_PER_MILE) / walk_speed_mph * 60.0
    else:
        # Auto-detect: check impedance name and mean weight.
        # If the impedance is named 'length' (typical for OSM data in meters),
        # or the mean weight is much larger than plausible walking times
        # (which would be < ~60 minutes for most urban edges), assume meters.
        impedance_is_length = (
            hasattr(net, "impedance_names")
            and net.impedance_names
            and net.impedance_names[0] == "length"
        )
        mean_weight = edges["weight"].mean()
        if impedance_is_length or mean_weight > 10:
            edges["weight"] = (edges["weight"] / METERS_PER_MILE) / walk_speed_mph * 60.0

    return OSMNetwork(edges=edges, nodes=nodes)


def integrate(
    transit: TransitNetwork,
    osm: Union[OSMNetwork, pandarm.Network],
    max_connector_dist: float = 800.0,
    walk_speed_mph: float = DEFAULT_WALK_SPEED_MPH,
    headways: Optional[pd.DataFrame] = None,
    headway_statistic: str = "mean",
    osm_weight_unit: str = "auto",
) -> IntegratedNetwork:
    """Integrate a transit network with an OSM pedestrian network.

    Creates connector edges between transit stops and the nearest OSM nodes,
    weighted by walking time. Optionally adds headway-based wait times.

    Parameters
    ----------
    transit : TransitNetwork
        Transit network edges and nodes.
    osm : OSMNetwork or pandarm.Network
        OSM pedestrian network edges and nodes, or an existing pandarm.Network.
    max_connector_dist : float, optional
        Maximum connector distance in meters (default 800).
    walk_speed_mph : float, optional
        Walking speed in mph (default 3.0).
    headways : pandas.DataFrame, optional
        Headway statistics DataFrame with 'route_id', 'stop_id', and statistic columns.
    headway_statistic : str, optional
        Column name in headways to use for wait time (default 'mean').
    osm_weight_unit : str, optional
        Unit of edge weights in the OSM/pandarm network. One of
        ``'auto'``, ``'meters'``, ``'minutes'``, or ``'seconds'``.
        Only used when *osm* is a ``pandarm.Network``. See
        :func:`_pandarm_to_osm_network` for details (default ``'auto'``).

    Returns
    -------
    IntegratedNetwork
    """
    # Normalize pandarm.Network to OSMNetwork
    if isinstance(osm, pandarm.Network):
        osm = _pandarm_to_osm_network(
            osm, walk_speed_mph=walk_speed_mph, weight_unit=osm_weight_unit
        )

    if not isinstance(osm, OSMNetwork):
        raise TypeError(
            f"osm must be an OSMNetwork or pandarm.Network, got {type(osm).__name__}"
        )

    if transit.edges.empty or transit.nodes.empty:
        raise EmptyNetworkError("Transit network is empty")
    if osm.edges.empty or osm.nodes.empty:
        raise EmptyNetworkError("OSM network is empty")

    # Build connector edges
    connectors = _build_connectors(
        transit.nodes,
        osm.nodes,
        max_connector_dist=max_connector_dist,
        walk_speed_mph=walk_speed_mph,
    )

    # Combine edges
    all_edges = _combine_edges(transit.edges, osm.edges, connectors)

    # Combine nodes
    all_nodes = _combine_nodes(transit.nodes, osm.nodes)

    # Add headway impedance if provided
    if headways is not None and not headways.empty:
        all_edges = _add_headway_impedance(all_edges, headways, headway_statistic)

    status(
        f"Integrated network: {len(all_nodes)} nodes, {len(all_edges)} edges "
        f"({len(connectors)} connectors)"
    )

    return IntegratedNetwork(
        edges=all_edges,
        nodes=all_nodes,
        connector_edges=connectors,
        transit_edges=transit.edges,
        transit_nodes=transit.nodes,
        osm_edges=osm.edges,
        osm_nodes=osm.nodes,
    )


def _build_connectors(
    transit_nodes: pd.DataFrame,
    osm_nodes: pd.DataFrame,
    max_connector_dist: float,
    walk_speed_mph: float,
) -> pd.DataFrame:
    """Build connector edges between transit stops and OSM nodes.

    Uses haversine distance for accurate geographic distance calculation.
    Finds the nearest OSM node to each transit stop within max_connector_dist
    and creates bidirectional connector edges weighted by walking time.
    """
    # Ensure coordinate columns exist
    if "x" not in transit_nodes.columns or "y" not in transit_nodes.columns:
        raise NetworkIntegrationError("Transit nodes must have 'x' and 'y' columns")
    if "x" not in osm_nodes.columns or "y" not in osm_nodes.columns:
        # osmnx uses 'lon' and 'lat' sometimes
        if "lon" in osm_nodes.columns and "lat" in osm_nodes.columns:
            osm_nodes = osm_nodes.rename(columns={"lon": "x", "lat": "y"})
        else:
            raise NetworkIntegrationError("OSM nodes must have 'x' and 'y' (or 'lon'/'lat') columns")

    # Normalize OSM node ID column
    osm_nodes_copy = osm_nodes.copy()
    if "node_id" not in osm_nodes_copy.columns and "osmid" in osm_nodes_copy.columns:
        osm_nodes_copy = osm_nodes_copy.rename(columns={"osmid": "node_id"})

    # Find nearest OSM node for each transit stop using BallTree
    # BallTree with haversine metric avoids allocating the full
    # (n_transit × n_osm) distance matrix — O(n log n) instead of O(n²)
    transit_coords = np.radians(transit_nodes[["y", "x"]].to_numpy(dtype=np.float64))
    osm_coords = np.radians(osm_nodes_copy[["y", "x"]].to_numpy(dtype=np.float64))
    tree = BallTree(osm_coords, metric="haversine")
    dist_radians, nearest_idx = tree.query(transit_coords, k=1)
    nearest_dist = dist_radians.ravel() * _EARTH_RADIUS_M
    nearest_idx = nearest_idx.ravel()

    # Filter by max distance
    valid_mask = nearest_dist <= max_connector_dist
    if not valid_mask.any():
        status("WARNING: No transit stops within max_connector_dist of OSM nodes")
        return pd.DataFrame(columns=["from", "to", "weight", "net_type"])

    valid_transit_idx = np.where(valid_mask)[0]
    valid_nearest_idx = nearest_idx[valid_mask]
    valid_distances_m = nearest_dist[valid_mask]

    transit_node_ids = transit_nodes.iloc[valid_transit_idx]["node_id"].values
    osm_node_ids = osm_nodes_copy.iloc[valid_nearest_idx]["node_id"].values

    # Compute walking time in minutes
    walk_times = (valid_distances_m / METERS_PER_MILE) / walk_speed_mph * 60.0

    # Build bidirectional connector edges
    connectors = pd.DataFrame({
        "from": np.concatenate([transit_node_ids, osm_node_ids]),
        "to": np.concatenate([osm_node_ids, transit_node_ids]),
        "weight": np.concatenate([walk_times, walk_times]),
        "net_type": ["transit to osm"] * len(transit_node_ids) + ["osm to transit"] * len(osm_node_ids),
    })

    # Add straight-line geometry for connector edges
    transit_x = transit_nodes.set_index("node_id").loc[transit_node_ids, "x"].values
    transit_y = transit_nodes.set_index("node_id").loc[transit_node_ids, "y"].values
    osm_x = osm_nodes_copy.set_index("node_id").loc[osm_node_ids, "x"].values
    osm_y = osm_nodes_copy.set_index("node_id").loc[osm_node_ids, "y"].values

    # Forward connectors: transit → osm
    forward_geoms = [
        LineString([(float(tx), float(ty)), (float(ox), float(oy))])
        for tx, ty, ox, oy in zip(transit_x, transit_y, osm_x, osm_y)
    ]
    # Reverse connectors: osm → transit (same geometry)
    reverse_geoms = forward_geoms

    connectors["geometry"] = forward_geoms + reverse_geoms

    status(f"Built {len(connectors)} connector edges for {len(transit_node_ids)} stops")
    return connectors.reset_index(drop=True)


def _combine_edges(
    transit_edges: pd.DataFrame,
    osm_edges: pd.DataFrame,
    connectors: pd.DataFrame,
) -> pd.DataFrame:
    """Combine transit, OSM, and connector edges into a single DataFrame.

    Preserves geometry columns if present in any of the input DataFrames.
    """
    # Ensure consistent columns
    common_cols = ["from", "to", "weight", "net_type"]
    t_edges = transit_edges.copy()
    o_edges = osm_edges.copy()
    c_edges = connectors.copy()

    for col in common_cols:
        if col not in t_edges.columns:
            t_edges[col] = np.nan
        if col not in o_edges.columns:
            o_edges[col] = np.nan
        if col not in c_edges.columns:
            c_edges[col] = np.nan

    # Add net_type if missing
    if "net_type" not in t_edges.columns:
        t_edges["net_type"] = "transit"
    if "net_type" not in o_edges.columns:
        o_edges["net_type"] = "osm"

    all_edges = pd.concat([t_edges, o_edges, c_edges], ignore_index=True)

    # Warn about negative weights — these break shortest-path algorithms.
    # Zero-weight edges are allowed (e.g., connector edges between coincident nodes).
    neg_count = (all_edges["weight"] < 0).sum()
    if neg_count > 0:
        _log(
            f"WARNING: {neg_count} edges with negative weight detected. "
            f"These will be dropped from the network."
        )
        all_edges = all_edges[all_edges["weight"] >= 0].copy()

    return all_edges.reset_index(drop=True)


def _combine_nodes(
    transit_nodes: pd.DataFrame,
    osm_nodes: pd.DataFrame,
) -> pd.DataFrame:
    """Combine transit and OSM nodes into a single DataFrame."""
    t_nodes = transit_nodes.copy()
    o_nodes = osm_nodes.copy()

    # Normalize OSM node ID column to match transit
    if "osmid" in o_nodes.columns and "node_id" not in o_nodes.columns:
        o_nodes = o_nodes.rename(columns={"osmid": "node_id"})
    elif "osmid" in o_nodes.columns:
        # Both exist — prefer node_id, drop osmid
        o_nodes = o_nodes.drop(columns=["osmid"])

    # Ensure consistent columns
    all_cols = set(t_nodes.columns).union(set(o_nodes.columns))
    for col in all_cols:
        if col not in t_nodes.columns:
            t_nodes[col] = np.nan
        if col not in o_nodes.columns:
            o_nodes[col] = np.nan

    all_nodes = pd.concat([t_nodes, o_nodes], ignore_index=True)
    return all_nodes.reset_index(drop=True)


def _add_headway_impedance(
    edges: pd.DataFrame,
    headways: pd.DataFrame,
    statistic: str = "mean",
) -> pd.DataFrame:
    """Add headway-based wait time to transit edges.

    Parameters
    ----------
    edges : pandas.DataFrame
        Integrated edges.
    headways : pandas.DataFrame
        Headway statistics with route_id and statistic columns.
    statistic : str, optional
        Statistic column to use (default 'mean').

    Returns
    -------
    pandas.DataFrame
        Edges with headway impedance added.
    """
    if statistic not in headways.columns:
        raise ValueError(f"Statistic '{statistic}' not found in headways DataFrame")

    # Merge headways into edges by route_id
    edges = edges.merge(
        headways[["route_id", statistic]],
        on="route_id",
        how="left",
    )

    # Add wait time to transit edges only
    mask = edges["net_type"] == "transit"
    edges.loc[mask, "weight"] = edges.loc[mask, "weight"] + edges.loc[mask, statistic].fillna(0)

    edges = edges.drop(columns=[statistic])
    return edges
