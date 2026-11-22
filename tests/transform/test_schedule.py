"""Tests for reading GTFS clock times."""

import numpy as np
import pandas as pd
import pytest

from netweave.exceptions import TimeFormatError
from netweave.transform import timetoseconds


def test_repeated_and_missing_times_keep_their_rows() -> None:
    times = pd.Series(
        ["08:00:00", None, "25:30:15", "08:00:00", " 08:00:00"], index=[5, 3, 9, 1, 7]
    )
    seconds = timetoseconds(times)
    assert seconds.index.tolist() == [5, 3, 9, 1, 7]
    # 25:30:15 is 25 * 3600 + 30 * 60 + 15.
    np.testing.assert_array_equal(
        seconds.to_numpy(), [28_800.0, np.nan, 91_815.0, 28_800.0, 28_800.0]
    )


def test_one_bad_time_among_repeats_raises() -> None:
    with pytest.raises(TimeFormatError):
        timetoseconds(pd.Series(["08:00:00"] * 3 + ["8am"]))
