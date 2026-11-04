"""Shared types and constants for netweave."""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

METERS_PER_MILE: float = 1609.344
DEFAULT_WALK_SPEED_MPH: float = 3.0


@dataclass(frozen=True, slots=True)
class TransitNetwork:
    """Container for a transit network's edges and nodes, and a record of its inputs."""

    edges: pd.DataFrame
    nodes: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.edges, pd.DataFrame):
            raise TypeError("edges must be a pandas DataFrame or geopandas GeoDataFrame")
        if not isinstance(self.nodes, pd.DataFrame):
            raise TypeError("nodes must be a pandas DataFrame or geopandas GeoDataFrame")
