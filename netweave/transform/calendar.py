"""Choose which GTFS service a transit network represents."""

import warnings

import pandas as pd

from netweave.exceptions import CalendarSelectionError
from netweave.io.gtfs import GTFSFeed

DAYS: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _exceptions(calendar_dates: pd.DataFrame, exception_type: str) -> pd.DataFrame:
    """Return the service and date of one kind of calendar exception."""
    if calendar_dates.empty:
        return pd.DataFrame(columns=["service_id", "date"])
    kept = calendar_dates["exception_type"].astype(str) == exception_type
    return calendar_dates.loc[kept, ["service_id", "date"]]


def _services_on(calendar: pd.DataFrame, calendar_dates: pd.DataFrame, date: str) -> set[str]:
    """Return the services running on one date: the weekly pattern plus its exceptions."""
    active: set[str] = set()
    if not calendar.empty:
        weekday = DAYS[pd.to_datetime(date, format="%Y%m%d").day_of_week]
        runs = (
            (calendar[weekday].astype(str) == "1")
            & (calendar["start_date"] <= date)
            & (calendar["end_date"] >= date)
        )
        active |= set(calendar.loc[runs, "service_id"])

    added = _exceptions(calendar_dates, "1")
    removed = _exceptions(calendar_dates, "2")
    active |= set(added.loc[added["date"] == date, "service_id"])
    active -= set(removed.loc[removed["date"] == date, "service_id"])
    return active


def _busiest_date(
    trips: pd.DataFrame,
    calendar: pd.DataFrame,
    calendar_dates: pd.DataFrame,
    day: str,
) -> str | None:
    """Return the date on one weekday with the most trips, the earliest if several tie."""
    pairs: list[pd.DataFrame] = []
    if not calendar.empty:
        frequency = f"W-{day[:3].upper()}"
        for row in calendar[calendar[day].astype(str) == "1"].itertuples():
            dates = pd.date_range(
                pd.to_datetime(row.start_date, format="%Y%m%d"),
                pd.to_datetime(row.end_date, format="%Y%m%d"),
                freq=frequency,
            )
            pairs.append(
                pd.DataFrame({"service_id": row.service_id, "date": dates.strftime("%Y%m%d")})
            )

    added = _exceptions(calendar_dates, "1")
    if not added.empty:
        weekdays = pd.to_datetime(added["date"], format="%Y%m%d").dt.day_of_week
        pairs.append(added[weekdays == DAYS.index(day)])

    if not pairs:
        return None

    scheduled = pd.concat(pairs, ignore_index=True).drop_duplicates()
    removed = _exceptions(calendar_dates, "2").assign(removed=True)
    scheduled = scheduled.merge(removed, how="left", on=["service_id", "date"])
    scheduled = scheduled[scheduled["removed"].isna()]

    trip_counts = trips.groupby("service_id").size().rename("trips").reset_index()
    per_date = scheduled.merge(trip_counts, on="service_id").groupby("date")["trips"].sum()
    if per_date.empty:
        return None
    return str(
        per_date.reset_index()
        .sort_values(["trips", "date"], ascending=[False, True])["date"]
        .iloc[0]
    )


def _of_feed(table: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Return the rows of a merged table that belong to one feed."""
    return table if table.empty else table[table["feed"] == prefix]


def select_service(
    feed: GTFSFeed,
    day: str | None = None,
    date: str | None = None,
) -> tuple[set[str], dict[str, str | None]]:
    """Choose the services a transit network represents, one date per original feed.

    ``date`` means that date in every feed. ``day`` means the busiest such
    weekday in each feed, chosen separately because the validity of different
    agencies' feeds need not overlap, and never a union of several dates, which
    would mix seasons and shorten headways that no rider experiences.

    Parameters
    ----------
    feed : GTFSFeed
        A merged feed.
    day : str, optional
        Day of the week, such as ``"monday"``.
    date : str, optional
        Date as ``YYYYMMDD``.

    Returns
    -------
    tuple
        The selected service IDs, and the date used for each feed prefix, which
        is None for a feed with no service.

    Raises
    ------
    ValueError
        If not exactly one of ``day`` and ``date`` is given, or if either is
        malformed.
    CalendarSelectionError
        If no feed has any service.
    """
    if (day is None) == (date is None):
        raise ValueError("Pass exactly one of day or date")
    if day is not None:
        day = day.lower()
        if day not in DAYS:
            raise ValueError(f"Unknown day '{day}': must be one of {', '.join(DAYS)}")
    else:
        try:
            pd.to_datetime(date, format="%Y%m%d")
        except ValueError as error:
            raise ValueError(f"Date '{date}' must be written as YYYYMMDD") from error

    requested = day or date
    service_ids: set[str] = set()
    dates: dict[str, str | None] = {}
    without_service: list[str] = []
    for source in feed.sources:
        prefix = source["prefix"]
        trips = _of_feed(feed.trips, prefix)
        calendar = _of_feed(feed.calendar, prefix)
        calendar_dates = _of_feed(feed.calendar_dates, prefix)
        chosen = date if day is None else _busiest_date(trips, calendar, calendar_dates, day)
        active = set() if chosen is None else _services_on(calendar, calendar_dates, chosen)
        if trips["service_id"].isin(active).any():
            service_ids |= active
            dates[prefix] = chosen
        else:
            without_service.append(prefix)
            dates[prefix] = None

    if not service_ids:
        raise CalendarSelectionError(f"No feed has service on {requested}")
    for prefix in without_service:
        warnings.warn(
            f"Feed '{prefix}' has no service on {requested}, so it adds nothing to this network",
            UserWarning,
            stacklevel=3,
        )
    return service_ids, dates
