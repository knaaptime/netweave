"""GTFS schedule processing: time parsing, interpolation, and unique IDs."""

from typing import Optional

import numpy as np
import pandas as pd

from netweave._logging import status
from netweave.exceptions import TimeFormatError


def timetoseconds(time_series: pd.Series) -> pd.Series:
    """Convert HH:MM:SS strings to seconds since midnight.

    Parameters
    ----------
    time_series : pandas.Series
        Series of time strings.

    Returns
    -------
    pandas.Series
        Seconds since midnight as integers.

    Raises
    ------
    TimeFormatError
        If a time string cannot be parsed.
    """
    # Handle times > 24:00:00 (e.g., 25:30:00 for next-day service)
    parts = time_series.str.split(":", expand=True)
    if parts.shape[1] != 3:
        raise TimeFormatError("Time strings must be in HH:MM:SS format")

    hours = parts[0].astype(int)
    minutes = parts[1].astype(int)
    seconds = parts[2].astype(int)

    return hours * 3600 + minutes * 60 + seconds


def seconds_to_time(seconds: pd.Series) -> pd.Series:
    """Convert seconds since midnight to HH:MM:SS strings.

    Parameters
    ----------
    seconds : pandas.Series
        Seconds since midnight.

    Returns
    -------
    pandas.Series
        Time strings in HH:MM:SS format.
    """
    hours = (seconds // 3600).astype(int)
    minutes = ((seconds % 3600) // 60).astype(int)
    secs = (seconds % 60).astype(int)
    return hours.astype(str).str.zfill(2) + ":" + minutes.astype(str).str.zfill(2) + ":" + secs.astype(str).str.zfill(2)


def add_unique_ids(
    df: pd.DataFrame,
    prefix: str,
    id_col: str = "unique_id",
) -> pd.DataFrame:
    """Add a unique ID column by concatenating agency/feed prefixes.

    Parameters
    ----------
    df : pandas.DataFrame
        Input DataFrame.
    prefix : str
        Prefix to prepend (e.g., agency_id or feed_id).
    id_col : str, optional
        Name of the new unique ID column.

    Returns
    -------
    pandas.DataFrame
        DataFrame with the new unique ID column.
    """
    df = df.copy()
    # Use the first column that looks like an ID as the base
    base_col = None
    for col in ["trip_id", "route_id", "stop_id", "agency_id"]:
        if col in df.columns:
            base_col = col
            break
    if base_col is None:
        raise ValueError("No suitable ID column found for unique ID generation")
    df[id_col] = prefix + "_" + df[base_col].astype(str)
    return df


def interpolate_stop_times(
    stop_times: pd.DataFrame,
    trip_ids: list[str],
    interpolate_missing: bool = True,
) -> pd.DataFrame:
    """Interpolate missing arrival/departure times in stop_times.

    Uses linear interpolation between known stop times for each trip.

    Parameters
    ----------
    stop_times : pandas.DataFrame
        GTFS stop_times table with 'trip_id', 'stop_sequence',
        'arrival_time', 'departure_time' columns.
    trip_ids : list[str]
        List of trip IDs to process.
    interpolate_missing : bool, optional
        If True (default), interpolate missing arrival/departure times.
        If False, skip interpolation and return stop_times as-is.
        Set to False when you know the feed has complete times.

    Returns
    -------
    pandas.DataFrame
        stop_times with interpolated times.
    """
    df = stop_times[stop_times["trip_id"].isin(trip_ids)].copy()
    if df.empty or not interpolate_missing:
        return df

    # Convert times to seconds
    for col in ["arrival_time", "departure_time"]:
        if col in df.columns:
            # Handle NaN/None values gracefully
            valid_mask = df[col].notna() & (df[col] != "")
            df[f"{col}_sec"] = pd.Series(index=df.index, dtype="Int64")
            if valid_mask.any():
                df.loc[valid_mask, f"{col}_sec"] = timetoseconds(df.loc[valid_mask, col])

    # Sort by trip and sequence
    df = df.sort_values(["trip_id", "stop_sequence"]).reset_index(drop=True)

    # Vectorized interpolation per trip using groupby().transform()
    for col in ["arrival_time_sec", "departure_time_sec"]:
        if col in df.columns:
            df[col] = df.groupby("trip_id")[col].transform(
                lambda x: x.interpolate(method="linear") if len(x) > 1 else x
            )

    # Convert back to HH:MM:SS
    for col in ["arrival_time_sec", "departure_time_sec"]:
        if col in df.columns:
            base = col.replace("_sec", "")
            df[base] = seconds_to_time(df[col].round().astype(int))
            df = df.drop(columns=[col])

    return df.reset_index(drop=True)


def select_by_time_range(
    df: pd.DataFrame,
    start_time: str,
    end_time: str,
    time_col: str = "departure_time",
    pad: Optional[str] = None,
) -> pd.DataFrame:
    """Select rows within a time range.

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame with a time column in HH:MM:SS format.
    start_time : str
        Start time in HH:MM:SS.
    end_time : str
        End time in HH:MM:SS.
    time_col : str, optional
        Column containing time strings.
    pad : str, optional
        Additional padding after end_time in HH:MM:SS format.

    Returns
    -------
    pandas.DataFrame
        Filtered DataFrame.
    """
    start_sec = timetoseconds(pd.Series([start_time])).iloc[0]
    end_sec = timetoseconds(pd.Series([end_time])).iloc[0]
    if pad is not None:
        pad_sec = timetoseconds(pd.Series([pad])).iloc[0]
        end_sec += pad_sec

    df = df.copy()
    df["_time_sec"] = timetoseconds(df[time_col])
    mask = (df["_time_sec"] >= start_sec) & (df["_time_sec"] <= end_sec)
    result = df.loc[mask].drop(columns=["_time_sec"]).copy()
    return result.reset_index(drop=True)
