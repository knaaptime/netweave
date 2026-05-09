"""Generic I/O utilities for netweave."""


from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def save_yaml(data: dict[str, Any], path: str | Path) -> None:
    """Save a dictionary to a YAML file.

    Parameters
    ----------
    data : dict
        Data to serialize.
    path : str or pathlib.Path
        Output file path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False)


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a dictionary from a YAML file.

    Parameters
    ----------
    path : str or pathlib.Path
        Input file path.

    Returns
    -------
    dict
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"YAML file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_geoparquet(
    df: pd.DataFrame,
    path: str | Path,
    index: bool = False,
) -> None:
    """Save a DataFrame to a GeoParquet file.

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame to save. If it contains a ``geometry`` column of
        ``shapely`` objects, it will be written as a GeoParquet file.
    path : str or pathlib.Path
        Output file path.
    index : bool, optional
        Whether to write the index.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import geopandas as gpd

        if isinstance(df, gpd.GeoDataFrame):
            df.to_parquet(path, index=index)
            return
    except ImportError:
        pass
    df.to_parquet(path, index=index)


def load_geoparquet(path: str | Path) -> pd.DataFrame:
    """Load a DataFrame from a GeoParquet file.

    Parameters
    ----------
    path : str or pathlib.Path
        Input file path.

    Returns
    -------
    pandas.DataFrame or geopandas.GeoDataFrame
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"GeoParquet file not found: {path}")
    try:
        import geopandas as gpd

        return gpd.read_parquet(path)
    except (ImportError, ValueError):
        # ValueError: missing geo metadata → fall back to pandas
        return pd.read_parquet(path)
