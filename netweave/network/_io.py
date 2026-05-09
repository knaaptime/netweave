"""Network I/O: save and load integrated networks."""


from pathlib import Path
from typing import Optional

import pandas as pd

from netweave._io import load_geoparquet, save_geoparquet
from netweave._logging import _log, status
from netweave.types import IntegratedNetwork


def save_network(
    network: IntegratedNetwork,
    path: str | Path,
    format: str = "geoparquet",
) -> None:
    """Save an integrated network to disk.

    Parameters
    ----------
    network : IntegratedNetwork
        Network to save.
    path : str or pathlib.Path
        Output directory or file path.
    format : str, optional
        Output format: 'geoparquet' or 'hdf5'.
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)

    if format == "geoparquet":
        save_geoparquet(network.edges, path / "edges.parquet")
        save_geoparquet(network.nodes, path / "nodes.parquet")
        save_geoparquet(network.connector_edges, path / "connectors.parquet")
        status(f"Network saved to {path} (GeoParquet)")
    elif format == "hdf5":
        _save_hdf5(network, path / "network.h5")
        status(f"Network saved to {path / 'network.h5'} (HDF5)")
    else:
        raise ValueError(f"Unknown format: {format}")


def load_network(
    path: str | Path,
    format: str = "geoparquet",
) -> IntegratedNetwork:
    """Load an integrated network from disk.

    Parameters
    ----------
    path : str or pathlib.Path
        Input directory or file path.
    format : str, optional
        Input format: 'geoparquet' or 'hdf5'.

    Returns
    -------
    IntegratedNetwork
    """
    path = Path(path)

    if format == "geoparquet":
        edges = load_geoparquet(path / "edges.parquet")
        nodes = load_geoparquet(path / "nodes.parquet")
        connectors = load_geoparquet(path / "connectors.parquet")
        status(f"Network loaded from {path} (GeoParquet)")
    elif format == "hdf5":
        return _load_hdf5(path / "network.h5")
    else:
        raise ValueError(f"Unknown format: {format}")

    return IntegratedNetwork(
        edges=edges,
        nodes=nodes,
        connector_edges=connectors,
        transit_edges=pd.DataFrame(),
        transit_nodes=pd.DataFrame(),
        osm_edges=pd.DataFrame(),
        osm_nodes=pd.DataFrame(),
    )


def _save_hdf5(network: IntegratedNetwork, path: Path) -> None:
    """Save network to HDF5 using pandas.HDFStore."""
    with pd.HDFStore(path, mode="w") as store:
        store.put("edges", _drop_geometry_if_geo(network.edges))
        store.put("nodes", _drop_geometry_if_geo(network.nodes))
        store.put("connectors", _drop_geometry_if_geo(network.connector_edges))
        store.put("transit_edges", _drop_geometry_if_geo(network.transit_edges))
        store.put("transit_nodes", _drop_geometry_if_geo(network.transit_nodes))
        store.put("osm_edges", _drop_geometry_if_geo(network.osm_edges))
        store.put("osm_nodes", _drop_geometry_if_geo(network.osm_nodes))


def _drop_geometry_if_geo(df: pd.DataFrame) -> pd.DataFrame:
    """Convert GeoDataFrame to plain DataFrame for HDF5 compatibility."""
    try:
        import geopandas as gpd
        if isinstance(df, gpd.GeoDataFrame):
            return pd.DataFrame(df.drop(columns="geometry"))
    except ImportError:
        pass
    return df


def _load_hdf5(path: Path) -> IntegratedNetwork:
    """Load network from HDF5 using pandas.HDFStore."""
    with pd.HDFStore(path, mode="r") as store:
        return IntegratedNetwork(
            edges=store["edges"],
            nodes=store["nodes"],
            connector_edges=store["connectors"],
            transit_edges=store["transit_edges"],
            transit_nodes=store["transit_nodes"],
            osm_edges=store["osm_edges"],
            osm_nodes=store["osm_nodes"],
        )
