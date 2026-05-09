"""GTFS feed container and validation."""


import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from netweave._logging import status
from netweave.exceptions import InvalidGTFS, MissingGTFSFile

# GTFS files required for a valid feed
REQUIRED_GTFS_FILES: list[str] = [
    "agency",
    "routes",
    "trips",
    "stop_times",
    "stops",
]

OPTIONAL_GTFS_FILES: list[str] = [
    "calendar",
    "calendar_dates",
    "shapes",
    "frequencies",
    "transfers",
    "feed_info",
]


@dataclass
class GTFSFeed:
    """Container for GTFS feed tables.

    Each attribute is a pandas DataFrame representing a GTFS file.
    Optional files default to empty DataFrames.
    """

    agency: pd.DataFrame = field(default_factory=pd.DataFrame)
    routes: pd.DataFrame = field(default_factory=pd.DataFrame)
    trips: pd.DataFrame = field(default_factory=pd.DataFrame)
    stop_times: pd.DataFrame = field(default_factory=pd.DataFrame)
    stops: pd.DataFrame = field(default_factory=pd.DataFrame)
    calendar: pd.DataFrame = field(default_factory=pd.DataFrame)
    calendar_dates: pd.DataFrame = field(default_factory=pd.DataFrame)
    shapes: pd.DataFrame = field(default_factory=pd.DataFrame)
    frequencies: pd.DataFrame = field(default_factory=pd.DataFrame)
    transfers: pd.DataFrame = field(default_factory=pd.DataFrame)
    feed_info: pd.DataFrame = field(default_factory=pd.DataFrame)

    def validate(self) -> None:
        """Validate that required files are present and have expected columns.

        Raises
        ------
        InvalidGTFS
            If validation fails.
        """
        missing: list[str] = []
        for name in REQUIRED_GTFS_FILES:
            df = getattr(self, name)
            if df.empty:
                missing.append(name)
        if missing:
            raise InvalidGTFS(
                f"Missing required GTFS file(s): {', '.join(missing)}"
            )

        # Basic column checks
        _expected = {
            "agency": ["agency_id", "agency_name"],
            "routes": ["route_id", "agency_id"],
            "trips": ["route_id", "trip_id", "service_id"],
            "stop_times": ["trip_id", "stop_id", "stop_sequence"],
            "stops": ["stop_id", "stop_lat", "stop_lon"],
            "calendar": [
                "service_id", "monday", "tuesday", "wednesday",
                "thursday", "friday", "saturday", "sunday",
                "start_date", "end_date",
            ],
            "calendar_dates": ["service_id", "date", "exception_type"],
            "frequencies": ["trip_id", "start_time", "end_time", "headway_secs"],
            "shapes": ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"],
        }
        for name, cols in _expected.items():
            df = getattr(self, name)
            if not df.empty:
                missing_cols = [c for c in cols if c not in df.columns]
                if missing_cols:
                    raise InvalidGTFS(
                        f"{name}.txt missing required column(s): {', '.join(missing_cols)}"
                    )

        # Foreign key sanity checks (soft — only warn)
        trip_ids = set(self.trips["trip_id"]) if "trip_id" in self.trips.columns else set()
        stop_ids = set(self.stops["stop_id"]) if "stop_id" in self.stops.columns else set()
        route_ids = set(self.routes["route_id"]) if "route_id" in self.routes.columns else set()

        if self.stop_times.empty:
            raise InvalidGTFS("stop_times is empty after loading")

        orphan_trips = set(self.stop_times["trip_id"]) - trip_ids
        if orphan_trips:
            status(
                f"WARNING: {len(orphan_trips)} trip_id(s) in stop_times "
                f"not found in trips.txt",
            )

        orphan_stops = set(self.stop_times["stop_id"]) - stop_ids
        if orphan_stops:
            status(
                f"WARNING: {len(orphan_stops)} stop_id(s) in stop_times "
                f"not found in stops.txt",
            )

        orphan_routes = set(self.trips["route_id"]) - route_ids
        if orphan_routes:
            status(
                f"WARNING: {len(orphan_routes)} route_id(s) in trips "
                f"not found in routes.txt",
            )

    def merge(self, other: "GTFSFeed", prefix: str | None = None) -> "GTFSFeed":
        """Merge another GTFSFeed into this one, concatenating all tables.

        Parameters
        ----------
        other : GTFSFeed
            Feed to merge.
        prefix : str, optional
            Prefix to prepend to all ID columns in ``other`` to avoid
            collisions when merging feeds from different sources.
            If provided, IDs like ``stop_id`` become ``{prefix}_stop_id``.

        Returns
        -------
        GTFSFeed
            A new feed with concatenated tables.
        """
        if prefix is not None:
            other = _prefix_feed_ids(other, prefix)

        kwargs: dict[str, pd.DataFrame] = {}
        for attr in [
            "agency", "routes", "trips", "stop_times", "stops",
            "calendar", "calendar_dates", "shapes", "frequencies",
            "transfers", "feed_info",
        ]:
            left = getattr(self, attr)
            right = getattr(other, attr)
            if left.empty and right.empty:
                kwargs[attr] = pd.DataFrame()
            elif left.empty:
                kwargs[attr] = right.copy()
            elif right.empty:
                kwargs[attr] = left.copy()
            else:
                kwargs[attr] = pd.concat([left, right], ignore_index=True)
        return GTFSFeed(**kwargs)

    @property
    def has_calendar(self) -> bool:
        """Return True if the calendar table is non-empty."""
        return not self.calendar.empty

    @property
    def has_calendar_dates(self) -> bool:
        """Return True if the calendar_dates table is non-empty."""
        return not self.calendar_dates.empty

    @property
    def has_frequencies(self) -> bool:
        """Return True if the frequencies table is non-empty."""
        return not self.frequencies.empty

    @property
    def has_shapes(self) -> bool:
        """Return True if the shapes table is non-empty."""
        return not self.shapes.empty


def _prefix_feed_ids(feed: GTFSFeed, prefix: str) -> GTFSFeed:
    """Prefix all ID columns in a GTFSFeed to avoid collisions.

    Updates both primary key columns and foreign key references.

    Parameters
    ----------
    feed : GTFSFeed
        Feed to prefix.
    prefix : str
        Prefix to prepend (e.g., "f0", "f1").

    Returns
    -------
    GTFSFeed
        New feed with prefixed IDs.
    """
    import copy

    feed = copy.deepcopy(feed)
    p = prefix

    # Primary ID columns that appear in multiple tables
    id_cols = {
        "agency_id": ["agency", "routes"],
        "route_id": ["routes", "trips"],
        "trip_id": ["trips", "stop_times", "frequencies"],
        "stop_id": ["stops", "stop_times", "transfers"],
        "service_id": ["calendar", "calendar_dates", "trips"],
        "shape_id": ["shapes", "trips"],
        "zone_id": ["stops"],
    }

    # Build mapping of old ID -> new ID for each column
    id_maps: dict[str, dict[str, str]] = {}
    for col, tables in id_cols.items():
        for table in tables:
            df = getattr(feed, table)
            if not df.empty and col in df.columns:
                if col not in id_maps:
                    id_maps[col] = {}
                for old_id in df[col].unique():
                    if old_id not in id_maps[col]:
                        id_maps[col][old_id] = f"{p}_{old_id}"

    # Apply prefixing to all tables
    for attr in [
        "agency", "routes", "trips", "stop_times", "stops",
        "calendar", "calendar_dates", "shapes", "frequencies",
        "transfers", "feed_info",
    ]:
        df = getattr(feed, attr)
        if df.empty:
            continue

        # Prefix primary ID columns
        for col in id_cols:
            if col in df.columns:
                df[col] = df[col].map(id_maps[col])

        # Special case: parent_station references stops.stop_id
        if "parent_station" in df.columns:
            df["parent_station"] = df["parent_station"].map(id_maps.get("stop_id", {}))

        # Special case: transfers has from_stop_id and to_stop_id
        if attr == "transfers":
            if "from_stop_id" in df.columns:
                df["from_stop_id"] = df["from_stop_id"].map(id_maps.get("stop_id", {}))
            if "to_stop_id" in df.columns:
                df["to_stop_id"] = df["to_stop_id"].map(id_maps.get("stop_id", {}))

    return feed


def load_feed(path: str | Path) -> GTFSFeed:
    """Load a GTFS feed from a zip file or directory.

    Parameters
    ----------
    path : str or pathlib.Path
        Path to a GTFS zip file or a directory containing GTFS text files.

    Returns
    -------
    GTFSFeed
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"GTFS path not found: {path}")

    if path.is_file() and path.suffix == ".zip":
        return _load_from_zip(path)
    elif path.is_dir():
        return _load_from_dir(path)
    else:
        raise ValueError(f"GTFS path must be a .zip file or directory: {path}")


def _load_from_zip(path: Path) -> GTFSFeed:
    """Load GTFS tables from a zip archive."""
    kwargs: dict[str, pd.DataFrame] = {}
    with zipfile.ZipFile(path, "r") as z:
        names = {Path(n).stem for n in z.namelist() if n.endswith(".txt")}
        for attr in [
            "agency", "routes", "trips", "stop_times", "stops",
            "calendar", "calendar_dates", "shapes", "frequencies",
            "transfers", "feed_info",
        ]:
            if attr in names:
                with z.open(f"{attr}.txt") as f:
                    kwargs[attr] = _read_gtfs_csv(f)
            else:
                kwargs[attr] = pd.DataFrame()
    return GTFSFeed(**kwargs)


def _load_from_dir(path: Path) -> GTFSFeed:
    """Load GTFS tables from a directory."""
    kwargs: dict[str, pd.DataFrame] = {}
    for attr in [
        "agency", "routes", "trips", "stop_times", "stops",
        "calendar", "calendar_dates", "shapes", "frequencies",
        "transfers", "feed_info",
    ]:
        file_path = path / f"{attr}.txt"
        if file_path.exists():
            kwargs[attr] = _read_gtfs_csv(file_path)
        else:
            kwargs[attr] = pd.DataFrame()
    return GTFSFeed(**kwargs)


def _read_gtfs_csv(path_or_buffer) -> pd.DataFrame:
    """Read a GTFS CSV file with optional pyarrow acceleration.

    Uses the pyarrow engine if available for faster parsing.
    Falls back to the default pandas engine otherwise.
    """
    read_kwargs = {
        "dtype": str,
        "keep_default_na": False,
        "na_values": ["", "\\N"],
        "encoding": "utf-8-sig",
    }
    try:
        import pyarrow  # noqa: F401
        read_kwargs["engine"] = "pyarrow"
    except ImportError:
        read_kwargs["low_memory"] = False
    return pd.read_csv(path_or_buffer, **read_kwargs)
