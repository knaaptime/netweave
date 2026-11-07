"""Read GTFS schedules: clock times, gaps in them, and frequency-based trips."""

import warnings

import numpy as np
import pandas as pd

from netweave.exceptions import TimeFormatError


def timetoseconds(times: pd.Series) -> pd.Series:
    """Convert HH:MM:SS strings to seconds since the start of the service day.

    Hours may pass 24, as GTFS allows for service running after midnight, and
    missing times stay missing.

    Parameters
    ----------
    times : pandas.Series
        Series of time strings.

    Returns
    -------
    pandas.Series
        Seconds as floats.

    Raises
    ------
    TimeFormatError
        If a time cannot be parsed.
    """
    seconds = pd.Series(np.nan, index=times.index, dtype=float)
    present = times.notna()
    if not present.any():
        return seconds

    parts = times[present].astype(str).str.strip().str.split(":", expand=True)
    if parts.shape[1] != 3:
        raise TimeFormatError("Time strings must be in HH:MM:SS format")
    numbers = parts.apply(pd.to_numeric, errors="coerce")
    if numbers.isna().to_numpy().any():
        raise TimeFormatError("Time strings must be in HH:MM:SS format")

    seconds[present] = numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    return seconds


def timed_stop_times(stop_times: pd.DataFrame, trip_ids: pd.Series) -> pd.DataFrame:
    """Return the stop times of some trips with a ``departure_sec`` for every row.

    Times left blank are interpolated evenly between the known times on either
    side. A row that cannot be timed, because its trip has no known time before
    or after it, is dropped with a warning.

    Parameters
    ----------
    stop_times : pandas.DataFrame
        GTFS stop_times table.
    trip_ids : pandas.Series
        The trips to keep.

    Returns
    -------
    pandas.DataFrame
        The rows of those trips in order along each trip.
    """
    timed = stop_times[stop_times["trip_id"].isin(trip_ids)].copy()

    def _seconds(column: str) -> pd.Series:
        if column in timed.columns:
            return timetoseconds(timed[column])
        return pd.Series(np.nan, index=timed.index, dtype=float)

    timed["departure_sec"] = _seconds("departure_time").fillna(_seconds("arrival_time"))
    timed = timed.sort_values(["trip_id", "stop_sequence"], kind="stable")

    blank = timed["departure_sec"].isna()
    if blank.any():
        affected = timed["trip_id"].isin(timed.loc[blank, "trip_id"])
        timed.loc[affected, "departure_sec"] = (
            timed[affected]
            .groupby("trip_id")["departure_sec"]
            .transform(lambda times: times.interpolate(limit_area="inside"))
        )
        untimed = timed["departure_sec"].isna()
        if untimed.any():
            warnings.warn(
                f"Dropped {int(untimed.sum())} stop times that could not be timed",
                UserWarning,
                stacklevel=3,
            )
            timed = timed[~untimed]
    return timed


def expand_frequencies(
    stop_times: pd.DataFrame,
    trips: pd.DataFrame,
    frequencies: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replace each frequency-based trip with one trip per scheduled departure.

    Parameters
    ----------
    stop_times : pandas.DataFrame
        Stop times with a ``departure_sec`` column.
    trips : pandas.DataFrame
        GTFS trips table.
    frequencies : pandas.DataFrame
        GTFS frequencies table.

    Returns
    -------
    tuple
        The stop times and trips, with templates replaced by their departures.
    """
    if frequencies.empty:
        return stop_times, trips
    periods = frequencies[
        frequencies["trip_id"].isin(stop_times["trip_id"]) & (frequencies["headway_secs"] > 0)
    ]
    if periods.empty:
        return stop_times, trips

    starts = timetoseconds(periods["start_time"])
    ends = timetoseconds(periods["end_time"])
    departures = pd.DataFrame(
        {
            "trip_id": periods["trip_id"].to_numpy(),
            "first_departure": [
                np.arange(start, end, step)
                for start, end, step in zip(starts, ends, periods["headway_secs"], strict=True)
            ],
        }
    ).explode("first_departure")
    departures = departures.dropna(subset=["first_departure"])
    departures["first_departure"] = departures["first_departure"].astype(float)
    departures["instance"] = (
        departures["trip_id"] + "#" + departures.groupby("trip_id").cumcount().astype(str)
    )

    is_template = stop_times["trip_id"].isin(periods["trip_id"])
    template_start = (
        stop_times[is_template].groupby("trip_id")["departure_sec"].min().rename("template_start")
    )
    expanded = (
        stop_times[is_template].merge(departures, on="trip_id").merge(template_start, on="trip_id")
    )
    expanded["departure_sec"] += expanded["first_departure"] - expanded["template_start"]
    expanded["trip_id"] = expanded["instance"]
    expanded = expanded.drop(columns=["first_departure", "instance", "template_start"])

    is_template_trip = trips["trip_id"].isin(periods["trip_id"])
    expanded_trips = trips[is_template_trip].merge(
        departures[["trip_id", "instance"]], on="trip_id"
    )
    expanded_trips["trip_id"] = expanded_trips["instance"]
    expanded_trips = expanded_trips.drop(columns="instance")

    return (
        pd.concat([stop_times[~is_template], expanded], ignore_index=True),
        pd.concat([trips[~is_template_trip], expanded_trips], ignore_index=True),
    )
