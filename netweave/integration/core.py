"""Join a transit network to a pedestrian network."""

import warnings

import geopandas as gpd
import numpy as np
import pandarm
import pandas as pd
import pyproj
import shapely
from sklearn.neighbors import BallTree

import netweave
from netweave._logging import status
from netweave.exceptions import EmptyNetworkError, NetworkIntegrationError
from netweave.integration.pandarm import build_network, pedestrian_tables
from netweave.transform.impedance import walk_minutes
from netweave.types import DEFAULT_WALK_SPEED_MPH, TransitNetwork

# Earth radius in meters (WGS-84 mean radius)
_EARTH_RADIUS_M: float = 6_371_008.8

_EDGE_COLUMNS: list[str] = [
    "from",
    "to",
    "edge_type",
    "minutes",
    "route_id",
    "direction_id",
    "geometry",
]


def integrate(
    transit: TransitNetwork,
    pedestrian: pandarm.Network,
    *,
    max_connector_dist: float = 800.0,
    walk_speed_mph: float = DEFAULT_WALK_SPEED_MPH,
    pedestrian_impedance: str | None = None,
    pedestrian_unit: str = "meters",
) -> pandarm.Network:
    """Join a transit network to a pedestrian network, every edge priced in minutes.

    Each stop connects to its nearest pedestrian node in both directions. The
    result uses the pedestrian network's CRS and keeps its node IDs, and transit
    nodes take integer IDs above them. It is always directed, so edges of a
    ``twoway=True`` input appear once in each direction.

    ``nodes_df`` gains ``node_type``, ``stop_id``, ``route_id``, ``direction_id``
    and ``feed``. ``edges_df`` gains ``edge_type``, ``route_id`` and
    ``direction_id``. ``metadata`` records what went into the network. Points
    given to ``get_node_ids`` and ``set_pois`` snap only to pedestrian nodes,
    while query results cover every node, so filter them on ``node_type``. These
    additions do not yet survive ``from_hdf5`` or ``to_crs``, so project the
    pedestrian network before integrating rather than after.

    Parameters
    ----------
    transit : TransitNetwork
        The transit network.
    pedestrian : pandarm.Network
        The pedestrian network, with integer node IDs. It is not changed.
    max_connector_dist : float, optional
        The furthest a stop may be from a pedestrian node, in meters (default 800).
    walk_speed_mph : float, optional
        Walking speed in miles per hour (default 3.0).
    pedestrian_impedance : str, optional
        The pedestrian impedance to use. May be omitted when there is only one.
    pedestrian_unit : {"meters", "minutes", "seconds"}, optional
        The unit of that impedance. The default suits ``Network.from_gdf``.

    Returns
    -------
    pandarm.Network
        The integrated network, with the impedance ``minutes``.

    Raises
    ------
    TypeError
        If ``pedestrian`` is not a ``pandarm.Network``.
    ValueError
        If the impedance or unit is not recognized.
    EmptyNetworkError
        If either network is empty.
    NetworkIntegrationError
        If pedestrian node IDs are not integers, if no stop can connect, or if a
        cost cannot be represented in pandarm.
    """
    if not isinstance(pedestrian, pandarm.Network):
        raise TypeError(f"pedestrian must be a pandarm.Network, got {type(pedestrian).__name__}")
    if transit.edges.empty or transit.nodes.empty:
        raise EmptyNetworkError("The transit network is empty")
    if pedestrian.edges_df.empty or pedestrian.nodes_df.empty:
        raise EmptyNetworkError("The pedestrian network is empty")

    walk_nodes, walk_edges, impedance = pedestrian_tables(
        pedestrian, pedestrian_impedance, pedestrian_unit, walk_speed_mph
    )
    if not pd.api.types.is_integer_dtype(walk_nodes.index):
        raise NetworkIntegrationError("The pedestrian network must have integer node IDs")

    crs = pyproj.CRS.from_user_input(pedestrian.crs)
    first_transit_id = int(walk_nodes.index.max()) + 1
    transit_nodes, transit_edges = _transit_tables(transit, crs, first_transit_id)

    stops = transit_nodes[transit_nodes["node_type"] == "stop"]
    connectors, stranded = _connectors(stops, walk_nodes, crs, max_connector_dist, walk_speed_mph)
    if stranded:
        warnings.warn(
            f"{stranded} stop(s) are more than {max_connector_dist:,.0f} m from the pedestrian "
            "network. Trips pass through them, but riders cannot reach them on foot.",
            UserWarning,
            stacklevel=2,
        )
    if connectors.empty:
        raise NetworkIntegrationError(
            f"No stop can connect to the pedestrian network within {max_connector_dist:,.0f} m"
        )

    walk_nodes = walk_nodes.assign(node_type="pedestrian")
    nodes = pd.concat([walk_nodes, transit_nodes.set_index("node_id")])
    edges = pd.concat(
        [walk_edges.assign(edge_type="walk"), transit_edges, connectors],
        ignore_index=True,
    ).reindex(columns=_EDGE_COLUMNS)

    metadata = {
        **transit.metadata,
        "pedestrian": {
            "impedance": impedance,
            "unit": pedestrian_unit,
            "crs": crs.to_string(),
            "twoway": bool(pedestrian._twoway),
        },
        "walk_speed_mph": walk_speed_mph,
        "max_connector_dist": max_connector_dist,
        "stranded_stops": stranded,
        "netweave_version": netweave.__version__,
    }
    status(f"Integrated network: {len(nodes)} nodes, {len(edges)} edges")
    return build_network(nodes, edges, pedestrian.crs, metadata, len(walk_nodes))


def _transit_tables(
    transit: TransitNetwork,
    crs: pyproj.CRS,
    first_id: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return a transit network's tables in a CRS, with node IDs starting at ``first_id``."""
    nodes = transit.nodes.copy()
    points = gpd.GeoSeries(gpd.points_from_xy(nodes["x"], nodes["y"]), crs=4326).to_crs(crs)
    nodes["x"], nodes["y"] = points.x.to_numpy(), points.y.to_numpy()
    nodes["node_id"] += first_id

    edges = pd.DataFrame(transit.edges.to_crs(crs))
    edges["from"] += first_id
    edges["to"] += first_id
    edges["geometry"] = edges["geometry"].to_numpy()
    return nodes, edges


def _connectors(
    stops: pd.DataFrame,
    walk_nodes: pd.DataFrame,
    crs: pyproj.CRS,
    max_dist: float,
    walk_speed_mph: float,
) -> tuple[pd.DataFrame, int]:
    """Join each stop to its nearest pedestrian node, if it is near enough.

    Distance is measured on the sphere for a geographic CRS, and on the plane
    in the units of a projected one.

    Returns
    -------
    tuple
        The connector edges, in both directions, and the number of stops left
        without any.
    """
    stop_xy = stops[["x", "y"]].to_numpy(dtype=float)
    walk_xy = walk_nodes[["x", "y"]].to_numpy(dtype=float)
    if crs.is_geographic:
        tree = BallTree(np.radians(walk_xy[:, ::-1]), metric="haversine")
        distance, nearest = tree.query(np.radians(stop_xy[:, ::-1]), k=1)
        meters = distance.ravel() * _EARTH_RADIUS_M
    else:
        tree = BallTree(walk_xy, metric="euclidean")
        distance, nearest = tree.query(stop_xy, k=1)
        meters = distance.ravel() * crs.axis_info[0].unit_conversion_factor
    nearest = nearest.ravel()

    near = meters <= max_dist
    stop_ids = stops["node_id"].to_numpy()[near]
    walk_ids = walk_nodes.index.to_numpy()[nearest[near]]
    minutes = walk_minutes(meters[near], walk_speed_mph)
    lines = shapely.linestrings(np.stack([stop_xy[near], walk_xy[nearest[near]]], axis=1))
    connectors = pd.DataFrame(
        {
            "from": np.concatenate([stop_ids, walk_ids]),
            "to": np.concatenate([walk_ids, stop_ids]),
            "edge_type": "connector",
            "minutes": np.concatenate([minutes, minutes]),
            "geometry": np.concatenate([lines, shapely.reverse(lines)]),
        }
    )
    return connectors, int((~near).sum())
