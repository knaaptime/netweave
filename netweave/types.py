"""Shared types, constants, and protocols for netweave."""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import geopandas as gpd
import pandas as pd

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------
METERS_PER_MILE: float = 1609.344
DEFAULT_WALK_SPEED_MPH: float = 3.0


# ---------------------------------------------------------------------------
# Network dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TransitNetwork:
    """Container for a transit network's edges and nodes, and a record of its inputs."""

    edges: pd.DataFrame
    nodes: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.edges, (pd.DataFrame, gpd.GeoDataFrame)):
            raise TypeError("edges must be a pandas DataFrame or geopandas GeoDataFrame")
        if not isinstance(self.nodes, (pd.DataFrame, gpd.GeoDataFrame)):
            raise TypeError("nodes must be a pandas DataFrame or geopandas GeoDataFrame")


@dataclass(frozen=True, slots=True)
class OSMNetwork:
    """Container for an OSM pedestrian network's edges and nodes."""

    edges: pd.DataFrame
    nodes: pd.DataFrame

    def __post_init__(self) -> None:
        if not isinstance(self.edges, (pd.DataFrame, gpd.GeoDataFrame)):
            raise TypeError("edges must be a pandas DataFrame or geopandas GeoDataFrame")
        if not isinstance(self.nodes, (pd.DataFrame, gpd.GeoDataFrame)):
            raise TypeError("nodes must be a pandas DataFrame or geopandas GeoDataFrame")


@dataclass(frozen=True, slots=True)
class IntegratedNetwork:
    """Container for an integrated transit + pedestrian network."""

    edges: pd.DataFrame
    nodes: pd.DataFrame
    connector_edges: pd.DataFrame
    transit_edges: pd.DataFrame
    transit_nodes: pd.DataFrame
    osm_edges: pd.DataFrame
    osm_nodes: pd.DataFrame

    def __post_init__(self) -> None:
        for name, df in [
            ("edges", self.edges),
            ("nodes", self.nodes),
            ("connector_edges", self.connector_edges),
            ("transit_edges", self.transit_edges),
            ("transit_nodes", self.transit_nodes),
            ("osm_edges", self.osm_edges),
            ("osm_nodes", self.osm_nodes),
        ]:
            if not isinstance(df, (pd.DataFrame, gpd.GeoDataFrame)):
                raise TypeError(f"{name} must be a pandas DataFrame or geopandas GeoDataFrame")


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------
@runtime_checkable
class OSMNetworkLoader(Protocol):
    """Protocol for OSM network loaders."""

    def load(self, bbox: tuple[float, float, float, float]) -> OSMNetwork:
        """Load an OSM network for the given bounding box.

        Parameters
        ----------
        bbox : tuple[float, float, float, float]
            Bounding box as (min_lat, min_lon, max_lat, max_lon).

        Returns
        -------
        OSMNetwork
        """
        ...
