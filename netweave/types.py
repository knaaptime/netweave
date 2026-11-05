"""Shared types and constants for netweave."""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

METERS_PER_MILE: float = 1609.344
DEFAULT_WALK_SPEED_MPH: float = 3.0


@dataclass(frozen=True, slots=True)
class TransitNetwork:
    """A transit network: its nodes, its edges, and a record of what went into them.

    Build one with :func:`netweave.create_transit_network`, and join it to a
    pedestrian network with :func:`netweave.integrate`.

    Attributes
    ----------
    edges : geopandas.GeoDataFrame
        One row per edge, with ``from``, ``to``, ``edge_type`` (``"ride"``,
        ``"board"`` or ``"alight"``), ``minutes``, ``route_id``,
        ``direction_id`` and ``geometry``, in EPSG:4326.
    nodes : pandas.DataFrame
        One row per node, with ``node_id``, ``x`` and ``y`` in longitude and
        latitude, ``node_type`` (``"stop"`` or ``"route_stop"``), ``stop_id``,
        ``route_id``, ``direction_id`` and ``feed``.
    metadata : dict
        The feeds and the service date each one used, the feeds left out and
        why, the time window, and whether boarding charges a wait.
    """

    edges: pd.DataFrame
    nodes: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.edges, pd.DataFrame):
            raise TypeError("edges must be a pandas DataFrame or geopandas GeoDataFrame")
        if not isinstance(self.nodes, pd.DataFrame):
            raise TypeError("nodes must be a pandas DataFrame or geopandas GeoDataFrame")
