"""Build a transit network from GTFS feeds.

A transit network is a graph with two kinds of node. A stop is a place, and a
route-stop is one route, in one direction where the feed records direction, at
one stop. Ride edges join consecutive route-stops. A boarding edge leads from a
stop to a route-stop and costs the wait for that route, and an alighting edge
leads back at no cost. Changing routes at a stop therefore costs the wait for
the next route and no walking.

The graph has no clock, so trips between the same two route-stops share one edge
priced at their mean time.
"""

import warnings
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.ops import substring

from netweave._logging import status
from netweave.exceptions import EmptyNetworkError
from netweave.io.gtfs import GTFSFeed, merge_feeds
from netweave.transform.calendar import select_service
from netweave.transform.headways import compute_headways
from netweave.transform.impedance import ride_minutes, wait_minutes
from netweave.transform.schedule import expand_frequencies, timed_stop_times, timetoseconds
from netweave.types import TransitNetwork

_ROUTE_STOP_KEY: list[str] = ["route_id", "direction_id", "stop_id"]


def create_transit_network(
    feed: GTFSFeed | list[GTFSFeed],
    *,
    timerange: tuple[str, str],
    day: str | None = None,
    date: str | None = None,
    use_headways: bool = True,
    prune: Any | None = None,
) -> TransitNetwork:
    """Create a transit network from one or more GTFS feeds.

    Parameters
    ----------
    feed : GTFSFeed or list of GTFSFeed
        The feed or feeds to build from. Several feeds are merged first. The
        input is not changed.
    timerange : tuple[str, str]
        The time window as (start, end) in HH:MM:SS on the GTFS clock, so
        ``("24:00:00", "26:00:00")`` on a Monday means early on Tuesday.
    day : str, optional
        Day of the week, such as ``"monday"``. Each feed uses its busiest such
        weekday. Pass exactly one of ``day`` and ``date``.
    date : str, optional
        Date as ``YYYYMMDD``, used in every feed.
    use_headways : bool, optional
        If True (default), a boarding edge costs half the mean headway of its
        route-stop. If False, boarding costs nothing.
    prune : tuple or numpy.ndarray or geopandas.GeoDataFrame or shapely geometry, optional
        Study area, as ``(minx, miny, maxx, maxy)`` in longitude and latitude or
        as a boundary. Stops outside it are dropped, and a route that leaves the
        area and returns gets one ride edge across the gap.

    Returns
    -------
    TransitNetwork
        Edges with ``from``, ``to``, ``edge_type``, ``minutes``, ``route_id``,
        ``direction_id`` and ``geometry``, and nodes with ``node_id``, ``x``,
        ``y``, ``node_type``, ``stop_id``, ``route_id``, ``direction_id`` and
        ``feed``, in EPSG:4326, and metadata recording what went into them.

    Raises
    ------
    ValueError
        If the selection or time window is malformed.
    CalendarSelectionError
        If no feed has service on the selected day.
    EmptyNetworkError
        If no ride edges can be built.
    """
    merged = merge_feeds(feed if isinstance(feed, list) else [feed])
    merged.validate()

    start, end = _window_seconds(timerange)
    service_ids, service_dates = select_service(merged, day=day, date=date)
    trips = merged.trips[merged.trips["service_id"].isin(service_ids)]

    stop_times = timed_stop_times(merged.stop_times, trips["trip_id"])
    stop_times, trips = expand_frequencies(stop_times, trips, merged.frequencies)
    stop_times = stop_times[stop_times["departure_sec"].between(start, end)]

    stops = merged.stops.drop_duplicates("stop_id")
    stop_times = _drop_stops_without_coordinates(stop_times, stops)
    if prune is not None:
        stop_times = stop_times[stop_times["stop_id"].isin(_stops_in_area(stops, prune))]
    if stop_times.empty:
        raise EmptyNetworkError("No departures at stops in the study area in the time window")

    rows = _rows_with_route_stops(stop_times, trips)
    hops = _hops(rows)
    if hops.empty:
        raise EmptyNetworkError("No ride edges can be built in the time window")

    ride = hops.groupby(["from", "to"], as_index=False)["minutes"].mean()
    wait = _wait_by_route_stop(rows, ride, (end - start) / 60.0, use_headways)
    edges, nodes = _assemble(ride, rows, stops, wait, hops, merged.shapes)

    metadata = {
        "feeds": [
            {**source, "service_date": service_dates[source["prefix"]]} for source in merged.sources
        ],
        "missing_feeds": merged.missing,
        "time_window": list(timerange),
        "use_headways": use_headways,
    }
    status(f"Transit network: {len(nodes)} nodes, {len(edges)} edges")
    return TransitNetwork(edges=edges, nodes=nodes, metadata=metadata)


def _window_seconds(timerange: tuple[str, str]) -> tuple[float, float]:
    """Return a time window as seconds, checking that it runs forwards."""
    start, end = timetoseconds(pd.Series(list(timerange)))
    if end <= start:
        raise ValueError(f"timerange must end after it starts, got {timerange}")
    return start, end


def _drop_stops_without_coordinates(
    stop_times: pd.DataFrame,
    stops: pd.DataFrame,
) -> pd.DataFrame:
    """Remove rows at stops that cannot be placed, warning about any that are used."""
    located = stops.dropna(subset=["stop_lat", "stop_lon"])["stop_id"]
    placed = stop_times["stop_id"].isin(located)
    if not placed.all():
        count = stop_times.loc[~placed, "stop_id"].nunique()
        warnings.warn(
            f"Skipped {count} stop(s) without coordinates",
            UserWarning,
            stacklevel=3,
        )
    return stop_times[placed]


def _stops_in_area(stops: pd.DataFrame, area: Any) -> pd.Series:
    """Return the IDs of stops inside a bounding box or boundary."""
    if isinstance(area, (tuple, list, np.ndarray)):
        if len(area) != 4:
            raise ValueError("prune must be a boundary or (minx, miny, maxx, maxy)")
        area = shapely.box(*area)
    elif isinstance(area, (gpd.GeoDataFrame, gpd.GeoSeries)):
        if area.crs is not None:
            area = area.to_crs(4326)
        area = area.union_all()
    points = shapely.points(stops["stop_lon"].to_numpy(), stops["stop_lat"].to_numpy())
    return stops.loc[shapely.intersects(points, area), "stop_id"]


def _rows_with_route_stops(stop_times: pd.DataFrame, trips: pd.DataFrame) -> pd.DataFrame:
    """Give each stop time its route, direction, shape, feed and route-stop."""
    columns = ["trip_id", "route_id", "feed"]
    columns += [column for column in ("direction_id", "shape_id") if column in trips.columns]
    rows = stop_times[["trip_id", "stop_id", "stop_sequence", "departure_sec"]].merge(
        trips[columns], on="trip_id"
    )
    for column in ("direction_id", "shape_id"):
        if column not in rows.columns:
            rows[column] = pd.NA
    rows["route_stop"] = rows.groupby(_ROUTE_STOP_KEY, dropna=False, sort=True).ngroup()
    return rows


def _hops(rows: pd.DataFrame) -> pd.DataFrame:
    """Return one row for each trip's movement between consecutive route-stops.

    A zero-time movement is kept, because schedules round to the minute and
    removing it would cut the route in two. A movement backwards in time is a
    data error and is dropped with a warning.
    """
    rows = rows.sort_values(["trip_id", "stop_sequence"], kind="stable")
    by_trip = rows.groupby("trip_id", sort=False)
    hops = rows.assign(
        to=by_trip["route_stop"].shift(-1),
        next_departure=by_trip["departure_sec"].shift(-1),
    ).dropna(subset=["to"])
    hops = hops.rename(columns={"route_stop": "from"})
    hops["to"] = hops["to"].astype("int64")
    hops["minutes"] = ride_minutes(hops["departure_sec"], hops["next_departure"])

    backwards = hops["minutes"] < 0
    if backwards.any():
        warnings.warn(
            f"Dropped {int(backwards.sum())} ride connection(s) that run backwards in time",
            UserWarning,
            stacklevel=3,
        )
    return hops[~backwards & (hops["from"] != hops["to"])]


def _wait_by_route_stop(
    rows: pd.DataFrame,
    ride: pd.DataFrame,
    window_minutes: float,
    use_headways: bool,
) -> pd.Series:
    """Return the wait at each route-stop that riders can board."""
    boardable = rows[rows["route_stop"].isin(ride["from"])]
    if not use_headways:
        return pd.Series(0.0, index=boardable["route_stop"].unique())
    headways = compute_headways(boardable, "route_stop", window_minutes)
    return wait_minutes(headways.set_index("route_stop")["headway"])


def _assemble(
    ride: pd.DataFrame,
    rows: pd.DataFrame,
    stops: pd.DataFrame,
    wait: pd.Series,
    hops: pd.DataFrame,
    shapes: pd.DataFrame,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Number the nodes and combine ride, boarding and alighting edges."""
    used = pd.unique(ride[["from", "to"]].to_numpy().ravel())
    route_stops = (
        rows[rows["route_stop"].isin(used)]
        .drop_duplicates("route_stop")
        .sort_values("route_stop")[["route_stop", "route_id", "direction_id", "stop_id"]]
    )
    used_stops = (
        stops[stops["stop_id"].isin(route_stops["stop_id"])]
        .sort_values("stop_id")
        .reset_index(drop=True)
    )

    stop_nodes = pd.DataFrame(
        {
            "node_id": np.arange(len(used_stops), dtype="int64"),
            "x": used_stops["stop_lon"].to_numpy(dtype=float),
            "y": used_stops["stop_lat"].to_numpy(dtype=float),
            "node_type": "stop",
            "stop_id": used_stops["stop_id"].to_numpy(),
            "route_id": pd.NA,
            "direction_id": pd.NA,
            "feed": used_stops["feed"].to_numpy(),
        }
    )
    stop_node_ids = stop_nodes.set_index("stop_id")["node_id"]
    located = stop_nodes.set_index("stop_id")

    route_stops = route_stops.reset_index(drop=True)
    route_stops["node_id"] = np.arange(len(route_stops), dtype="int64") + len(stop_nodes)
    route_stops["stop_node"] = route_stops["stop_id"].map(stop_node_ids)
    route_stop_nodes = pd.DataFrame(
        {
            "node_id": route_stops["node_id"],
            "x": route_stops["stop_id"].map(located["x"]),
            "y": route_stops["stop_id"].map(located["y"]),
            "node_type": "route_stop",
            "stop_id": route_stops["stop_id"],
            "route_id": route_stops["route_id"],
            "direction_id": route_stops["direction_id"],
            "feed": route_stops["stop_id"].map(located["feed"]),
        }
    )
    nodes = pd.concat([stop_nodes, route_stop_nodes], ignore_index=True)

    by_route_stop = route_stops.set_index("route_stop")
    ride_edges = pd.DataFrame(
        {
            "from": ride["from"].map(by_route_stop["node_id"]).to_numpy(),
            "to": ride["to"].map(by_route_stop["node_id"]).to_numpy(),
            "edge_type": "ride",
            "minutes": ride["minutes"].to_numpy(),
            "route_id": ride["from"].map(by_route_stop["route_id"]).to_numpy(),
            "direction_id": ride["from"].map(by_route_stop["direction_id"]).to_numpy(),
        }
    )
    boarding = by_route_stop.loc[by_route_stop.index.isin(ride["from"])]
    board_edges = pd.DataFrame(
        {
            "from": boarding["stop_node"].to_numpy(),
            "to": boarding["node_id"].to_numpy(),
            "edge_type": "board",
            "minutes": wait.reindex(boarding.index).to_numpy(),
            "route_id": boarding["route_id"].to_numpy(),
            "direction_id": boarding["direction_id"].to_numpy(),
        }
    )
    alighting = by_route_stop.loc[by_route_stop.index.isin(ride["to"])]
    alight_edges = pd.DataFrame(
        {
            "from": alighting["node_id"].to_numpy(),
            "to": alighting["stop_node"].to_numpy(),
            "edge_type": "alight",
            "minutes": 0.0,
            "route_id": alighting["route_id"].to_numpy(),
            "direction_id": alighting["direction_id"].to_numpy(),
        }
    )
    edges = pd.concat([ride_edges, board_edges, alight_edges], ignore_index=True)

    route_stop_xy = pd.DataFrame(
        {
            "x": route_stops["stop_id"].map(located["x"]).to_numpy(),
            "y": route_stops["stop_id"].map(located["y"]).to_numpy(),
        },
        index=route_stops["route_stop"].to_numpy(),
    )
    geometry = np.full(len(edges), None, dtype=object)
    geometry[: len(ride_edges)] = _ride_geometries(ride, hops, route_stop_xy, shapes)
    return gpd.GeoDataFrame(edges, geometry=geometry, crs="EPSG:4326"), nodes


def _shape_lines(shapes: pd.DataFrame) -> pd.Series:
    """Return a LineString for each shape with at least two usable points."""
    points = shapes.dropna(subset=["shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"])
    points = points.sort_values(["shape_id", "shape_pt_sequence"], kind="stable")
    points = points[points.groupby("shape_id")["shape_id"].transform("size") >= 2]
    if points.empty:
        return pd.Series(dtype=object)
    positions, shape_ids = pd.factorize(points["shape_id"])
    lines = shapely.linestrings(
        points[["shape_pt_lon", "shape_pt_lat"]].to_numpy(), indices=positions
    )
    return pd.Series(lines, index=shape_ids, dtype=object)


def _ride_geometries(
    ride: pd.DataFrame,
    hops: pd.DataFrame,
    route_stop_xy: pd.DataFrame,
    shapes: pd.DataFrame,
) -> np.ndarray:
    """Return the path of each ride edge.

    Each edge follows the most common shape among its trips, cut between its two
    stops. It falls back to a straight line where there is no shape, or where
    the stops do not fall in order along the shape.
    """
    start = route_stop_xy.loc[ride["from"]].to_numpy()
    end = route_stop_xy.loc[ride["to"]].to_numpy()
    lines = shapely.linestrings(np.stack([start, end], axis=1))
    if shapes.empty or hops["shape_id"].isna().all():
        return lines

    shape_lines = _shape_lines(shapes)
    usual_shape = (
        hops.dropna(subset=["shape_id"])
        .groupby(["from", "to", "shape_id"])
        .size()
        .rename("trips")
        .reset_index()
        .sort_values(["trips", "shape_id"], ascending=[False, True])
        .drop_duplicates(["from", "to"])
    )
    chosen = ride[["from", "to"]].merge(usual_shape, how="left", on=["from", "to"])["shape_id"]
    candidates = chosen.map(shape_lines)
    has_shape = candidates.notna().to_numpy()
    if not has_shape.any():
        return lines

    shaped = candidates[has_shape].to_numpy()
    from_position = shapely.line_locate_point(shaped, shapely.points(start[has_shape]))
    to_position = shapely.line_locate_point(shaped, shapely.points(end[has_shape]))
    for index, line, first, last in zip(
        np.flatnonzero(has_shape), shaped, from_position, to_position, strict=True
    ):
        if first < last:
            lines[index] = substring(line, first, last)
    return lines
