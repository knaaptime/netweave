"""GTFS calendar and service ID selection."""


import datetime
from typing import Optional

import pandas as pd

from netweave._logging import status
from netweave.exceptions import CalendarSelectionError

_DAY_MAP: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def select_service_ids(
    calendar: pd.DataFrame,
    calendar_dates: pd.DataFrame,
    day: Optional[str] = None,
    date: Optional[str] = None,
    date_range: Optional[tuple[str, str]] = None,
    calendar_dates_lookup: Optional[dict[str, str | list[str]]] = None,
) -> list[str]:
    """Select active service IDs based on calendar and calendar_dates.

    Parameters
    ----------
    calendar : pandas.DataFrame
        GTFS calendar table.
    calendar_dates : pandas.DataFrame
        GTFS calendar_dates table.
    day : str, optional
        Day of week (e.g., 'monday').
    date : str, optional
        Specific date in YYYYMMDD format.
    date_range : tuple[str, str], optional
        Date range as (start, end) in YYYYMMDD format.
    calendar_dates_lookup : dict, optional
        Exact-match lookup for calendar_dates columns.

    Returns
    -------
    list[str]
        Active service IDs.

    Raises
    ------
    CalendarSelectionError
        If no service IDs are selected.
    """
    service_ids: set[str] = set()

    if not calendar.empty and day is not None:
        day_col = day.lower()
        if day_col not in _DAY_MAP:
            raise ValueError(f"Invalid day: {day}. Must be one of {_DAY_MAP.keys()}")
        mask = calendar[day_col].astype(str) == "1"
        if date is not None:
            mask &= (calendar["start_date"] <= date) & (calendar["end_date"] >= date)
        elif date_range is not None:
            start, end = date_range
            mask &= (calendar["start_date"] <= end) & (calendar["end_date"] >= start)
        service_ids.update(calendar.loc[mask, "service_id"].unique())

    if not calendar_dates.empty:
        cd_mask = calendar_dates["exception_type"].astype(str) == "1"
        if date is not None:
            cd_mask &= calendar_dates["date"] == date
        elif date_range is not None:
            start, end = date_range
            cd_mask &= (calendar_dates["date"] >= start) & (calendar_dates["date"] <= end)
        elif day is not None:
            # Select dates that fall on the given day of week
            target_dow = _DAY_MAP[day.lower()]
            dates = pd.to_datetime(calendar_dates["date"], format="%Y%m%d")
            cd_mask &= dates.dt.dayofweek == target_dow
        if calendar_dates_lookup is not None:
            for col, val in calendar_dates_lookup.items():
                if isinstance(val, list):
                    cd_mask &= calendar_dates[col].isin(val)
                else:
                    cd_mask &= calendar_dates[col] == val
        service_ids.update(calendar_dates.loc[cd_mask, "service_id"].unique())

    if not service_ids:
        raise CalendarSelectionError(
            "No active service IDs found for the given selection criteria."
        )

    status(f"Selected {len(service_ids)} active service ID(s)")
    return sorted(service_ids)


def highest_frequency_date(
    trips: pd.DataFrame,
    calendar: pd.DataFrame,
    calendar_dates: pd.DataFrame,
) -> str:
    """Find the date with the highest number of trips.

    Parameters
    ----------
    trips : pandas.DataFrame
        GTFS trips table.
    calendar : pandas.DataFrame
        GTFS calendar table.
    calendar_dates : pandas.DataFrame
        GTFS calendar_dates table.

    Returns
    -------
    str
        Date in YYYYMMDD format with the most trips.
    """
    if calendar.empty and calendar_dates.empty:
        raise CalendarSelectionError("Both calendar and calendar_dates are empty")

    # Compute trips per service_id
    trip_counts = trips.groupby("service_id").size().reset_index(name="trip_count")

    all_service_dates: list[pd.DataFrame] = []

    # Build daily service coverage from calendar
    if not calendar.empty:
        cal = calendar.copy()
        cal["start_date"] = pd.to_datetime(cal["start_date"], format="%Y%m%d")
        cal["end_date"] = pd.to_datetime(cal["end_date"], format="%Y%m%d")

        # Get overall date range
        min_date = cal["start_date"].min()
        max_date = cal["end_date"].max()
        all_dates = pd.date_range(min_date, max_date, freq="D")

        # Create date -> day_of_week mapping
        dow_map = {0: "monday", 1: "tuesday", 2: "wednesday", 3: "thursday",
                   4: "friday", 5: "saturday", 6: "sunday"}
        date_df = pd.DataFrame({"date_dt": all_dates})
        date_df["dow"] = date_df["date_dt"].dt.dayofweek.map(dow_map)
        date_df["date"] = date_df["date_dt"].dt.strftime("%Y%m%d")

        # Melt calendar to (service_id, dow, start_date, end_date)
        day_cols = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        cal_melted = cal.melt(
            id_vars=["service_id", "start_date", "end_date"],
            value_vars=day_cols,
            var_name="dow",
            value_name="active",
        )
        cal_melted = cal_melted[cal_melted["active"].astype(str) == "1"]

        # Merge with dates and filter by range
        cal_expanded = cal_melted.merge(date_df, on="dow", how="inner")
        cal_expanded = cal_expanded[
            (cal_expanded["date_dt"] >= cal_expanded["start_date"]) &
            (cal_expanded["date_dt"] <= cal_expanded["end_date"])
        ][["service_id", "date"]]

        all_service_dates.append(cal_expanded)

    # Add calendar_dates exceptions
    if not calendar_dates.empty:
        cd = calendar_dates[calendar_dates["exception_type"].astype(str) == "1"][["service_id", "date"]].copy()
        all_service_dates.append(cd)

    if not all_service_dates:
        raise CalendarSelectionError("No active service dates found")

    # Combine all (service_id, date) pairs
    combined = pd.concat(all_service_dates, ignore_index=True).drop_duplicates()

    # Count trips per date
    date_trip_counts = combined.merge(trip_counts, on="service_id", how="inner")
    date_totals = date_trip_counts.groupby("date")["trip_count"].sum().reset_index()

    if date_totals.empty:
        raise CalendarSelectionError("No trips found for any active service date")

    best_date = date_totals.loc[date_totals["trip_count"].idxmax(), "date"]
    best_count = date_totals["trip_count"].max()
    status(f"Highest frequency date: {best_date} with {best_count} trips")
    return str(best_date)
