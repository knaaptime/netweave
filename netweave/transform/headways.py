"""Measure headways from scheduled departures."""

import pandas as pd


def compute_headways(
    departures: pd.DataFrame,
    by: str | list[str],
    window_minutes: float,
) -> pd.DataFrame:
    """Return the headway that a rider arriving at a random moment experiences, in minutes.

    A rider who arrives at random is more likely to land in a long gap between
    departures than in a short one, so the headway they experience is the mean gap
    weighted by its length: the sum of the squared gaps divided by the length of the
    window. The gap after the last departure runs round to the first, as if the
    window repeated. For departures evenly spaced across the window this is the
    ordinary headway, and for a single departure it is the length of the window.
    Half of it is the expected wait.

    Parameters
    ----------
    departures : pandas.DataFrame
        Departures inside the window, with a ``departure_sec`` column and the
        grouping columns.
    by : str or list of str
        Columns that identify a group, such as a route-stop.
    window_minutes : float
        The length of the time window.

    Returns
    -------
    pandas.DataFrame
        The grouping columns and ``headway``.
    """
    by = [by] if isinstance(by, str) else list(by)
    distinct = (
        departures[[*by, "departure_sec"]].drop_duplicates().sort_values([*by, "departure_sec"])
    )
    minutes = distinct["departure_sec"] / 60.0
    groups = [distinct[column] for column in by]
    by_group = minutes.groupby(groups, dropna=False)

    gaps = by_group.diff()
    squared = (gaps**2).groupby(groups, dropna=False).sum()
    wrap = (window_minutes - (by_group.max() - by_group.min())).clip(lower=0.0)
    headway = (squared + wrap**2) / window_minutes
    return headway.rename("headway").reset_index()
