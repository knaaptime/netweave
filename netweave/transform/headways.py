"""Measure headways from scheduled departures."""

import pandas as pd


def compute_headways(
    departures: pd.DataFrame,
    by: str | list[str],
    window_minutes: float,
) -> pd.DataFrame:
    """Return the mean time between departures of each group, in minutes.

    A group with a single departure has no gaps to measure, so the length of the
    window stands in for its headway. Departures at the same moment count once.

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
    gaps = distinct.groupby(by, dropna=False)["departure_sec"].diff()
    mean_gap = gaps.groupby([distinct[column] for column in by], dropna=False).mean() / 60.0
    return mean_gap.fillna(window_minutes).rename("headway").reset_index()
