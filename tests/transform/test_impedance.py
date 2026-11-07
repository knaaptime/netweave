"""Tests for converting costs to minutes, against worked values."""

import numpy as np
import pytest

from netweave.transform.impedance import ride_minutes, to_minutes, wait_minutes, walk_minutes


def test_walk_minutes_at_three_miles_an_hour() -> None:
    # 3 mph is 3 * 1609.344 / 60 = 80.4672 meters per minute.
    assert walk_minutes(80.4672) == pytest.approx(1.0)
    assert walk_minutes(804.672) == pytest.approx(10.0)


def test_walk_minutes_at_another_speed() -> None:
    assert walk_minutes(160.9344, walk_speed_mph=6.0) == pytest.approx(1.0)


def test_walk_minutes_of_an_array() -> None:
    assert walk_minutes(np.array([0.0, 80.4672])) == pytest.approx([0.0, 1.0])


def test_wait_is_half_the_headway() -> None:
    assert wait_minutes(12.5) == pytest.approx(6.25)


def test_ride_minutes_between_departures() -> None:
    assert ride_minutes(28800.0, 29160.0) == pytest.approx(6.0)


def test_to_minutes_from_each_unit() -> None:
    assert to_minutes(80.4672, "meters") == pytest.approx(1.0)
    assert to_minutes(120.0, "seconds") == pytest.approx(2.0)
    assert to_minutes(7.0, "minutes") == pytest.approx(7.0)


def test_to_minutes_uses_walking_speed_for_meters() -> None:
    assert to_minutes(160.9344, "meters", walk_speed_mph=6.0) == pytest.approx(1.0)


def test_to_minutes_refuses_an_unknown_unit() -> None:
    with pytest.raises(ValueError, match="furlongs"):
        to_minutes(1.0, "furlongs")
