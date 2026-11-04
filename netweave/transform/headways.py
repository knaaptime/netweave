"""GTFS headway statistics."""


import pandas as pd

from netweave._logging import status


def compute_headways(
    stop_times: pd.DataFrame,
    trips: pd.DataFrame,
    routes: pd.DataFrame,
    stops: pd.DataFrame,
    by: str = "route_stop",
) -> pd.DataFrame:
    """Compute headway statistics for a GTFS feed.

    Headways are the time between consecutive vehicle arrivals at a stop
    for a given route. The default statistic is mean headway / 2,
    representing average passenger wait time under uniform arrival.

    Parameters
    ----------
    stop_times : pandas.DataFrame
        GTFS stop_times table.
    trips : pandas.DataFrame
        GTFS trips table.
    routes : pandas.DataFrame
        GTFS routes table.
    stops : pandas.DataFrame
        GTFS stops table.
    by : str, optional
        Grouping level. Currently only 'route_stop' is supported.

    Returns
    -------
    pandas.DataFrame
        Headway statistics with columns:
        - route_id, stop_id
        - mean, std, min, max, median headways in minutes
    """
    if by != "route_stop":
        raise ValueError("Only by='route_stop' is currently supported")

    # Merge trip info into stop_times
    df = stop_times.merge(trips[["trip_id", "route_id"]], on="trip_id", how="left")

    # Convert departure_time to seconds
    from netweave.transform.schedule import timetoseconds
    df["departure_sec"] = timetoseconds(df["departure_time"])

    # Sort by route, stop, and time
    df = df.sort_values(["route_id", "stop_id", "departure_sec"]).reset_index(drop=True)

    # Vectorized headway calculation using groupby diff
    df["headway_sec"] = df.groupby(["route_id", "stop_id"])["departure_sec"].diff()

    # Filter out negative or zero headways (crossing midnight, data errors)
    df = df[df["headway_sec"] > 0].copy()

    if df.empty:
        status("WARNING: No valid headways could be computed")
        return pd.DataFrame()

    # Aggregate statistics
    stats = (
        df.groupby(["route_id", "stop_id"])["headway_sec"]
        .agg(["mean", "std", "min", "max", "median"])
        .reset_index()
    )

    # Convert to minutes
    for col in ["mean", "std", "min", "max", "median"]:
        stats[col] = stats[col] / 60.0

    status(f"Computed headways for {len(stats)} route-stop pairs")
    return stats
