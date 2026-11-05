"""Express every cost in the network in the one impedance they share: minutes."""

from typing import Any

from netweave.types import DEFAULT_WALK_SPEED_MPH, METERS_PER_MILE

UNITS: tuple[str, ...] = ("meters", "minutes", "seconds")


def walk_minutes(meters: Any, walk_speed_mph: float = DEFAULT_WALK_SPEED_MPH) -> Any:
    """Return the minutes needed to walk a distance.

    Parameters
    ----------
    meters : float or array-like
        Distance in meters.
    walk_speed_mph : float, optional
        Walking speed in miles per hour (default 3.0).

    Returns
    -------
    float or array-like
        Walking time in minutes.
    """
    return meters / METERS_PER_MILE / walk_speed_mph * 60.0


def ride_minutes(departure_sec: Any, next_departure_sec: Any) -> Any:
    """Return the minutes from one departure to the next, dwell included.

    Parameters
    ----------
    departure_sec : float or array-like
        Departure from a stop, in seconds since the start of the service day.
    next_departure_sec : float or array-like
        Departure from the next stop on the same trip, in the same units.

    Returns
    -------
    float or array-like
        Ride time in minutes.
    """
    return (next_departure_sec - departure_sec) / 60.0


def wait_minutes(headway_minutes: Any) -> Any:
    """Return the expected wait for a rider who arrives at a random moment.

    A rider who arrives without consulting the timetable waits, on average, half
    the time between departures.

    Parameters
    ----------
    headway_minutes : float or array-like
        Mean time between departures, in minutes.

    Returns
    -------
    float or array-like
        Expected wait in minutes.
    """
    return headway_minutes / 2.0


def to_minutes(values: Any, unit: str, walk_speed_mph: float = DEFAULT_WALK_SPEED_MPH) -> Any:
    """Convert costs to minutes, treating distances as walking.

    Parameters
    ----------
    values : float or array-like
        Costs in ``unit``.
    unit : {"meters", "minutes", "seconds"}
        The unit of ``values``.
    walk_speed_mph : float, optional
        Walking speed, used only for distances.

    Returns
    -------
    float or array-like
        Costs in minutes.

    Raises
    ------
    ValueError
        If the unit is not recognized.
    """
    if unit == "meters":
        return walk_minutes(values, walk_speed_mph)
    if unit == "seconds":
        return values / 60.0
    if unit == "minutes":
        return values
    raise ValueError(f"Unknown unit '{unit}': must be one of {', '.join(UNITS)}")
