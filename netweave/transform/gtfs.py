"""GTFS transit network generation."""

from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

from netweave._logging import _log, status
from netweave.exceptions import EmptyNetworkError
from netweave.transform.calendar import select_service_ids
from netweave.io.gtfs import GTFSFeed
from netweave.transform.schedule import (
    interpolate_stop_times,
    select_by_time_range,
    timetoseconds,
)
from netweave.types import TransitNetwork


def create_transit_network(
    feed: GTFSFeed,
    day: str | None = None,
    timerange: tuple[str, str] | None = None,
    date: str | None = None,
    date_range: tuple[str, str] | None = None,
    calendar_dates_lookup: dict[str, str | list[str]] | None = None,
    use_highest_freq_date: bool = False,
    simplify: bool = False,
    interpolate_missing: bool = True,
    prune: tuple[float, float, float, float] | Any | None = None,
) -> TransitNetwork:
    """Create a transit network from a GTFS feed.

    Parameters
    ----------
    feed : GTFSFeed
        Validated GTFS feed.
    day : str, optional
        Day of week (e.g., 'monday').
    timerange : tuple[str, str], optional
        Time range as (start, end) in HH:MM:SS.
    date : str, optional
        Specific date in YYYYMMDD format.
    date_range : tuple[str, str], optional
        Date range as (start, end) in YYYYMMDD.
    calendar_dates_lookup : dict, optional
        Exact-match lookup for calendar_dates.
    use_highest_freq_date : bool, optional
        If True, automatically select the date with the most trips.
    simplify : bool, optional
        If True, simplify the network by removing duplicate edges.
    interpolate_missing : bool, optional
        If True (default), interpolate missing arrival/departure times.
        If False, skip interpolation. Set to False for feeds with complete
        stop times to speed up network creation.
    prune : tuple[float, float, float, float] or GeoDataFrame or Polygon, optional
        Study area to prune the network to. Only stops inside this area
        are kept, and trips/routes without stops in the area are removed.
        - Bounding box: ``(minx, miny, maxx, maxy)`` to match
          ``geopandas.total_bounds``.
        - Polygon: ``geopandas.GeoDataFrame`` or ``shapely.geometry.Polygon``.

    Returns
    -------
    TransitNetwork
    """
    feed.validate()

    if use_highest_freq_date:
        from netweave.transform.calendar import highest_frequency_date
        date = highest_frequency_date(feed.trips, feed.calendar, feed.calendar_dates)

    # Select active service IDs
    service_ids = select_service_ids(
        feed.calendar,
        feed.calendar_dates,
        day=day,
        date=date,
        date_range=date_range,
        calendar_dates_lookup=calendar_dates_lookup,
    )

    # Select trips
    active_trips = feed.trips[feed.trips["service_id"].isin(service_ids)].copy()
    if active_trips.empty:
        raise EmptyNetworkError("No active trips found for the given criteria")

    trip_ids = active_trips["trip_id"].unique().tolist()

    # Interpolate stop times
    stop_times = interpolate_stop_times(
        feed.stop_times, trip_ids, interpolate_missing=interpolate_missing
    )
    if stop_times.empty:
        raise EmptyNetworkError("No stop times found for active trips")

    # Filter by time range
    if timerange is not None:
        stop_times = select_by_time_range(
            stop_times, timerange[0], timerange[1], time_col="departure_time"
        )
        if stop_times.empty:
            raise EmptyNetworkError("No stop times within the specified time range")

    # Prune to study area if requested
    if prune is not None:
        feed.stops, stop_times, active_trips, feed.routes = _prune_to_area(
            feed.stops, stop_times, active_trips, feed.routes, prune
        )
        if stop_times.empty:
            raise EmptyNetworkError("No stops found within the pruned study area")

    # Build edges
    edges = _build_edges(stop_times, active_trips, feed.routes)
    if edges.empty:
        raise EmptyNetworkError("No edges could be generated from stop times")

    # Build nodes
    nodes = _build_nodes(feed.stops, stop_times)

    # Assign geometry to edges
    edges = _assign_shape_to_edges(edges, active_trips, feed.shapes, nodes)

    # Simplify if requested
    if simplify:
        edges, nodes = _simplify_network(edges, nodes)

    # Add network type
    edges["net_type"] = "transit"
    nodes["net_type"] = "transit"

    status(f"Transit network: {len(nodes)} nodes, {len(edges)} edges")
    return TransitNetwork(edges=edges, nodes=nodes)


def _build_edges(
    stop_times: pd.DataFrame,
    trips: pd.DataFrame,
    routes: pd.DataFrame,
) -> pd.DataFrame:
    """Build transit edges from stop_times.

    Creates edges between consecutive stops within each trip,
    weighted by travel time in seconds.
    """
    # Merge trip and route info
    df = stop_times.merge(trips[["trip_id", "route_id"]], on="trip_id", how="left")
    df = df.merge(routes[["route_id", "route_type"]], on="route_id", how="left")

    # Compute departure time in seconds
    df["departure_sec"] = timetoseconds(df["departure_time"])

    # Sort by trip and sequence
    df = df.sort_values(["trip_id", "stop_sequence"]).reset_index(drop=True)

    # Vectorized edge creation using shift
    df["next_stop_id"] = df.groupby("trip_id")["stop_id"].shift(-1)
    df["next_departure_sec"] = df.groupby("trip_id")["departure_sec"].shift(-1)
    df["next_trip_id"] = df.groupby("trip_id")["trip_id"].shift(-1)

    # Only keep rows where the next row is the same trip
    mask = df["trip_id"] == df["next_trip_id"]
    edges = df.loc[mask].copy()

    if edges.empty:
        return pd.DataFrame()

    edges["weight"] = edges["next_departure_sec"] - edges["departure_sec"]
    edges["weight"] = edges["weight"] / 60.0  # convert to minutes

    # Filter out edges with non-positive weights. These can arise from
    # GTFS data quality issues (e.g., stops out of chronological order
    # within a trip) or trips that wrap past midnight without proper
    # 24:00:00+ formatting. Negative or zero travel times are not
    # physically meaningful for a routing network.
    n_before = len(edges)
    edges = edges[edges["weight"] > 0].copy()
    n_dropped = n_before - len(edges)
    if n_dropped > 0:
        status(
            f"Dropped {n_dropped} transit edges with non-positive weight "
            f"({n_before} → {len(edges)})"
        )

    # Rename columns
    edges = edges.rename(columns={
        "stop_id": "from",
        "next_stop_id": "to",
        "trip_id": "unique_trip_id",
        "route_id": "unique_route_id",
    })

    # Convert back to int after shift introduced NaN (all NaN rows were filtered out)
    import contextlib
    for col in ["from", "to", "unique_trip_id", "unique_route_id", "route_type"]:
        if col in edges.columns:
            with contextlib.suppress(ValueError, TypeError):
                edges[col] = edges[col].astype("int64")

    # Select and order columns
    edge_cols = ["from", "to", "weight", "unique_trip_id", "unique_route_id", "route_type"]
    edges = edges[[c for c in edge_cols if c in edges.columns]].copy()

    return edges.reset_index(drop=True)


def _build_nodes(stops: pd.DataFrame, stop_times: pd.DataFrame) -> pd.DataFrame:
    """Build transit nodes from stops that appear in stop_times."""
    used_stops = stop_times["stop_id"].unique()
    nodes = stops[stops["stop_id"].isin(used_stops)].copy()
    nodes = nodes.rename(columns={
        "stop_id": "node_id",
        "stop_lat": "y",
        "stop_lon": "x",
    })
    return nodes.reset_index(drop=True)


def _prune_to_area(
    stops: pd.DataFrame,
    stop_times: pd.DataFrame,
    trips: pd.DataFrame,
    routes: pd.DataFrame,
    prune: tuple[float, float, float, float] | Any,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Filter stops, stop_times, trips, and routes to only those inside a study area.

    Parameters
    ----------
    stops : pandas.DataFrame
        GTFS stops table with 'stop_lat' and 'stop_lon' columns.
    stop_times : pandas.DataFrame
        GTFS stop_times table.
    trips : pandas.DataFrame
        GTFS trips table.
    routes : pandas.DataFrame
        GTFS routes table.
    prune : tuple or GeoDataFrame or Polygon
        Study area boundary.
        - Bounding box: ``(minx, miny, maxx, maxy)`` to match
          ``geopandas.total_bounds``.
        - Polygon: ``geopandas.GeoDataFrame`` or ``shapely.geometry.Polygon``.

    Returns
    -------
    tuple
        (pruned_stops, pruned_stop_times, pruned_trips, pruned_routes)
    """

    stops = stops.copy()
    stops["stop_lon"] = pd.to_numeric(stops["stop_lon"], errors="coerce")
    stops["stop_lat"] = pd.to_numeric(stops["stop_lat"], errors="coerce")

    if isinstance(prune, tuple):
        if len(prune) != 4:
            raise ValueError("prune bbox must be a tuple of 4 floats (minx, miny, maxx, maxy)")
        minx, miny, maxx, maxy = prune
        mask = (
            (stops["stop_lon"] >= minx)
            & (stops["stop_lon"] <= maxx)
            & (stops["stop_lat"] >= miny)
            & (stops["stop_lat"] <= maxy)
        )
        pruned_stops = stops.loc[mask].copy()
    else:
        # Assume GeoDataFrame or shapely Polygon
        try:
            import geopandas as gpd
            area_geom = prune.unary_union if isinstance(prune, gpd.GeoDataFrame) else prune
            # Build a GeoDataFrame of stops
            stops_gdf = gpd.GeoDataFrame(
                stops,
                geometry=gpd.points_from_xy(stops["stop_lon"], stops["stop_lat"]),
                crs="EPSG:4326",
            )
            # Use .intersects for robust geometric filtering
            mask = stops_gdf["geometry"].intersects(area_geom)
            pruned_stops = stops_gdf.loc[mask].copy()
            # Drop geometry column to return as DataFrame, not GeoDataFrame
            pruned_stops = pruned_stops.drop(columns=["geometry"])
        except ImportError as err:
            raise ImportError("geopandas and shapely are required for polygon prune input") from err

    if pruned_stops.empty:
        return pruned_stops, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # Filter stop_times to those with stop_id in pruned stops
    pruned_stop_ids = set(pruned_stops["stop_id"])
    pruned_stop_times = stop_times[stop_times["stop_id"].isin(pruned_stop_ids)].copy()

    # Filter trips to those with trip_id in pruned stop_times
    pruned_trip_ids = set(pruned_stop_times["trip_id"])
    pruned_trips = trips[trips["trip_id"].isin(pruned_trip_ids)].copy()

    # Filter routes to those with route_id in pruned trips
    pruned_route_ids = set(pruned_trips["route_id"])
    pruned_routes = routes[routes["route_id"].isin(pruned_route_ids)].copy()

    status(
        f"Pruned to study area: {len(pruned_stops)} stops, "
        f"{len(pruned_stop_times)} stop_times, {len(pruned_trips)} trips, "
        f"{len(pruned_routes)} routes"
    )

    return pruned_stops, pruned_stop_times, pruned_trips, pruned_routes


def _simplify_network(
    edges: pd.DataFrame, nodes: pd.DataFrame
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Simplify the network by removing duplicate edges.

    Keeps only one edge per (from, to, weight, route_type) combination.
    Preserves the geometry column and GeoDataFrame type if present.
    """
    # Detect if edges is a GeoDataFrame
    is_geo = isinstance(edges, gpd.GeoDataFrame)
    crs = edges.crs if is_geo else None

    # Group by edge attributes and keep first
    group_cols = ["from", "to", "weight", "route_type"]
    group_cols = [c for c in group_cols if c in edges.columns]
    simp_edges = edges.groupby(group_cols, as_index=False).first()

    # Restore GeoDataFrame if needed
    if is_geo and "geometry" in simp_edges.columns:
        simp_edges = gpd.GeoDataFrame(simp_edges, geometry="geometry", crs=crs)

    # Remove nodes not in edges
    used_nodes = set(simp_edges["from"]).union(set(simp_edges["to"]))
    simp_nodes = nodes[nodes["node_id"].isin(used_nodes)].copy()

    _log(
        f"Simplified: {len(edges)} -> {len(simp_edges)} edges, "
        f"{len(nodes)} -> {len(simp_nodes)} nodes"
    )
    return simp_edges, simp_nodes


def _build_shape_geometries(shapes: pd.DataFrame) -> gpd.GeoDataFrame:
    """Build LineString geometries from GTFS shapes.txt data.

    For each shape_id, sorts points by shape_pt_sequence and constructs
    a LineString from (shape_pt_lon, shape_pt_lat) coordinates.

    Parameters
    ----------
    shapes : pandas.DataFrame
        GTFS shapes table with columns: shape_id, shape_pt_lat,
        shape_pt_lon, shape_pt_sequence.

    Returns
    -------
    geopandas.GeoDataFrame
        GeoDataFrame with columns: shape_id, geometry.
        Each geometry is a shapely LineString. CRS is EPSG:4326.
    """
    if shapes.empty:
        return gpd.GeoDataFrame(columns=["shape_id", "geometry"], crs="EPSG:4326")

    geometries = []
    for shape_id, group in shapes.sort_values("shape_pt_sequence").groupby("shape_id"):
        coords = list(
            zip(
                group["shape_pt_lon"].astype(float),
                group["shape_pt_lat"].astype(float),
                strict=True,
            )
        )
        if len(coords) >= 2:
            geometries.append({"shape_id": shape_id, "geometry": LineString(coords)})
        else:
            _log(f"WARNING: shape_id '{shape_id}' has fewer than 2 points, skipping")

    return gpd.GeoDataFrame(geometries, crs="EPSG:4326")


def _build_stop_geometries(
    edges: pd.DataFrame,
    nodes: pd.DataFrame,
) -> gpd.GeoSeries:
    """Build straight-line geometries between consecutive stops.

    For each edge (from, to), creates a LineString from the
    coordinates of the from-stop to the to-stop.

    Parameters
    ----------
    edges : pandas.DataFrame
        Edge DataFrame with 'from' and 'to' columns referencing node IDs.
    nodes : pandas.DataFrame
        Node DataFrame with 'node_id', 'x', and 'y' columns.

    Returns
    -------
    geopandas.GeoSeries
        GeoSeries of shapely LineString geometries, one per edge row.
        CRS is EPSG:4326.
    """
    # Build coordinate lookup from nodes
    node_coords = nodes.set_index("node_id")[["x", "y"]]

    geometries = []
    for _, row in edges.iterrows():
        try:
            from_coord = node_coords.loc[row["from"]]
            to_coord = node_coords.loc[row["to"]]
            geometries.append(LineString([
                (float(from_coord["x"]), float(from_coord["y"])),
                (float(to_coord["x"]), float(to_coord["y"])),
            ]))
        except KeyError:
            # If a node is missing, use a degenerate line (will be filtered later)
            geometries.append(None)

    return gpd.GeoSeries(geometries, index=edges.index, crs="EPSG:4326")


def _assign_shape_to_edges(
    edges: pd.DataFrame,
    trips: pd.DataFrame,
    shapes: pd.DataFrame,
    nodes: pd.DataFrame,
) -> gpd.GeoDataFrame:
    """Assign geometry to transit edges using shapes.txt when available.

    Uses GTFS shape data to build accurate route geometries. Falls back
    to straight-line segments between stops when a trip has no shape_id
    or the shape_id is not found in shapes.txt.

    Parameters
    ----------
    edges : pandas.DataFrame
        Edge DataFrame with 'unique_trip_id' column.
    trips : pandas.DataFrame
        Trips DataFrame with 'trip_id' and optionally 'shape_id' columns.
    shapes : pandas.DataFrame
        GTFS shapes table (may be empty).
    nodes : pandas.DataFrame
        Node DataFrame with 'node_id', 'x', 'y' columns.

    Returns
    -------
    geopandas.GeoDataFrame
        Edge GeoDataFrame with an active 'geometry' column of shapely
        LineStrings. CRS is EPSG:4326.
    """
    # Always compute stop-to-stop fallback geometries
    fallback_geoms = _build_stop_geometries(edges, nodes)

    # If no shapes data, use fallback for all edges
    if shapes.empty:
        edges = edges.copy()
        edges["geometry"] = fallback_geoms
        return gpd.GeoDataFrame(edges, geometry="geometry", crs="EPSG:4326")

    # Build shape geometries from shapes.txt
    shape_geoms = _build_shape_geometries(shapes)

    if shape_geoms.empty:
        edges = edges.copy()
        edges["geometry"] = fallback_geoms
        return gpd.GeoDataFrame(edges, geometry="geometry", crs="EPSG:4326")

    # Map trip_id → shape_id
    trip_shape = trips[["trip_id"]].copy()
    if "shape_id" in trips.columns:
        trip_shape["shape_id"] = trips["shape_id"]
    else:
        trip_shape["shape_id"] = pd.NA

    # Map shape_id → geometry
    shape_geom_map = shape_geoms.set_index("shape_id")["geometry"]

    # Join shape_id onto edges via unique_trip_id
    edges = edges.copy()

    # unique_trip_id may be int; trip_id in trips is string after GTFS load
    # Ensure consistent types for merge
    trip_shape["trip_id"] = trip_shape["trip_id"].astype(str)
    edges["_trip_id_str"] = edges["unique_trip_id"].astype(str)

    edges = edges.merge(
        trip_shape[["trip_id", "shape_id"]],
        left_on="_trip_id_str",
        right_on="trip_id",
        how="left",
    ).drop(columns=["_trip_id_str", "trip_id"])

    # Map shape geometry onto edges
    if not edges["shape_id"].isna().all():
        edges["shape_geom"] = edges["shape_id"].map(shape_geom_map)
    else:
        edges["shape_geom"] = None

    # Use shape geometry where available, fallback otherwise
    edges["geometry"] = edges["shape_geom"].where(edges["shape_geom"].notna(), fallback_geoms)
    edges = edges.drop(columns=["shape_id", "shape_geom"])

    return gpd.GeoDataFrame(edges, geometry="geometry", crs="EPSG:4326")
