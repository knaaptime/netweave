"""Visualization utilities for netweave networks."""


from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.collections import LineCollection

from netweave._logging import status


def plot_network(
    edges: pd.DataFrame,
    nodes: Optional[pd.DataFrame] = None,
    column: Optional[str] = None,
    bbox: Optional[tuple[float, float, float, float]] = None,
    figsize: tuple[float, float] = (10, 10),
    cmap: str = "viridis",
    ax: Optional[plt.Axes] = None,
) -> plt.Axes:
    """Plot a network using matplotlib.

    Parameters
    ----------
    edges : pandas.DataFrame
        Edges with 'from', 'to', and optionally 'weight' columns.
    nodes : pandas.DataFrame, optional
        Nodes with 'x', 'y' columns. Required if edges don't have geometry.
    column : str, optional
        Column to color edges by.
    bbox : tuple[float, float, float, float], optional
        Bounding box as (min_x, min_y, max_x, max_y).
    figsize : tuple[float, float], optional
        Figure size.
    cmap : str, optional
        Colormap name.
    ax : matplotlib.axes.Axes, optional
        Axes to plot on. If None, creates new figure.

    Returns
    -------
    matplotlib.axes.Axes
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)

    # If edges have geometry, use geopandas plotting
    if "geometry" in edges.columns:
        try:
            import geopandas as gpd
            gdf = gpd.GeoDataFrame(edges, geometry="geometry")
            gdf.plot(column=column, cmap=cmap, ax=ax, linewidth=0.5)
            if bbox is not None:
                ax.set_xlim(bbox[0], bbox[2])
                ax.set_ylim(bbox[1], bbox[3])
            return ax
        except ImportError:
            pass

    # Fallback: manual line collection
    if nodes is None:
        raise ValueError("nodes required when edges don't have geometry")

    # Build node coordinate lookup
    node_coords = nodes.set_index("node_id")[["x", "y"]]

    # Build line segments
    segments = []
    for _, row in edges.iterrows():
        try:
            from_node = node_coords.loc[row["from"]]
            to_node = node_coords.loc[row["to"]]
            segments.append([(from_node["x"], from_node["y"]), (to_node["x"], to_node["y"])])
        except KeyError:
            continue

    if not segments:
        status("WARNING: No valid segments to plot")
        return ax

    lc = LineCollection(segments, cmap=cmap, linewidths=0.5)
    if column is not None and column in edges.columns:
        lc.set_array(edges[column].values)

    ax.add_collection(lc)
    ax.autoscale()

    if bbox is not None:
        ax.set_xlim(bbox[0], bbox[2])
        ax.set_ylim(bbox[1], bbox[3])

    ax.set_aspect("equal")
    ax.set_title("Network")
    return ax
