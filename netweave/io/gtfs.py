"""GTFS feed container, loading, validation and merging."""

import warnings
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import pandas as pd

from netweave.exceptions import InvalidGTFS

# GTFS files required for a valid feed
REQUIRED_GTFS_FILES: tuple[str, ...] = ("agency", "routes", "trips", "stop_times", "stops")

OPTIONAL_GTFS_FILES: tuple[str, ...] = (
    "calendar",
    "calendar_dates",
    "shapes",
    "frequencies",
    "transfers",
    "feed_info",
)

_GTFS_TABLES: tuple[str, ...] = REQUIRED_GTFS_FILES + OPTIONAL_GTFS_FILES

_ID_COLUMNS: tuple[str, ...] = (
    "agency_id",
    "route_id",
    "trip_id",
    "stop_id",
    "service_id",
    "shape_id",
    "zone_id",
    "parent_station",
    "from_stop_id",
    "to_stop_id",
    "from_route_id",
    "to_route_id",
    "from_trip_id",
    "to_trip_id",
)

_TABLES_RECORDING_FEED: tuple[str, ...] = (
    "agency",
    "routes",
    "trips",
    "stops",
    "calendar",
    "calendar_dates",
)

_NUMERIC_COLUMNS: tuple[str, ...] = (
    "stop_sequence",
    "stop_lat",
    "stop_lon",
    "shape_pt_lat",
    "shape_pt_lon",
    "shape_pt_sequence",
    "headway_secs",
)

_EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "agency": ("agency_name",),
    "routes": ("route_id",),
    "trips": ("route_id", "trip_id", "service_id"),
    "stop_times": ("trip_id", "stop_id", "stop_sequence"),
    "stops": ("stop_id", "stop_lat", "stop_lon"),
    "calendar": (
        "service_id",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "start_date",
        "end_date",
    ),
    "calendar_dates": ("service_id", "date", "exception_type"),
    "frequencies": ("trip_id", "start_time", "end_time", "headway_secs"),
    "shapes": ("shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"),
}


def _as_text(values: pd.Series) -> pd.Series:
    """Return identifiers as text, leaving missing values missing."""
    if pd.api.types.is_string_dtype(values):
        return values
    present = values.notna()
    text = values.astype(object)
    text[present] = values[present].astype(str)
    return text


def _normalized(table: pd.DataFrame) -> pd.DataFrame:
    """Give a GTFS table text identifiers and numeric ordering and coordinate columns."""
    if table.empty:
        return table
    table = table.copy(deep=False)
    for column in _ID_COLUMNS:
        if column in table.columns:
            table[column] = _as_text(table[column])
    for column in _NUMERIC_COLUMNS:
        if column in table.columns:
            table[column] = pd.to_numeric(table[column], errors="coerce")
    return table


@dataclass
class GTFSFeed:
    """Container for GTFS feed tables.

    Each table attribute is a pandas DataFrame representing a GTFS file, and
    optional files default to empty DataFrames. Identifiers are always text;
    ``stop_sequence``, coordinates and ``headway_secs`` are always numeric.

    Parameters
    ----------
    name, onestop_id, feed_key : str, optional
        Where the feed came from, when known.
    sources : list of dict
        One record per original feed, filled in when feeds are merged.
    missing : list of dict
        Feeds that were requested but could not be supplied, with reasons.
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
    name: str | None = None
    onestop_id: str | None = None
    feed_key: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        for table in _GTFS_TABLES:
            setattr(self, table, _normalized(getattr(self, table)))

    def validate(self) -> None:
        """Check that required tables and columns are present and readable.

        Raises
        ------
        InvalidGTFS
            If a required table or column is missing, if ``agency_id`` is
            absent where a feed has several agencies, or if ``stop_sequence``
            holds values that are not numbers.
        """
        missing = [name for name in REQUIRED_GTFS_FILES if getattr(self, name).empty]
        if missing:
            raise InvalidGTFS(f"Missing required GTFS file(s): {', '.join(missing)}")

        for name, columns in _EXPECTED_COLUMNS.items():
            table = getattr(self, name)
            if table.empty:
                continue
            absent = [column for column in columns if column not in table.columns]
            if absent:
                raise InvalidGTFS(f"{name}.txt missing required column(s): {', '.join(absent)}")

        self._check_agency_ids()

        if self.stop_times["stop_sequence"].isna().any():
            raise InvalidGTFS("stop_times.txt has stop_sequence values that are not numbers")

        self._warn_about_orphans()

    def _check_agency_ids(self) -> None:
        """Require ``agency_id`` only where one feed lists several agencies."""
        agencies = self.agency
        by_feed = agencies.groupby("feed") if "feed" in agencies.columns else [(None, agencies)]
        for _, group in by_feed:
            if len(group) < 2:
                continue
            if "agency_id" not in group.columns or group["agency_id"].isna().any():
                raise InvalidGTFS("agency.txt needs agency_id when a feed has several agencies")
            if "agency_id" not in self.routes.columns:
                raise InvalidGTFS("routes.txt needs agency_id when a feed has several agencies")

    def _warn_about_orphans(self) -> None:
        """Warn about references to trips, stops or routes that a feed never defines."""
        checks = (
            ("trip_id", self.stop_times, self.trips, "stop_times", "trips"),
            ("stop_id", self.stop_times, self.stops, "stop_times", "stops"),
            ("route_id", self.trips, self.routes, "trips", "routes"),
        )
        for column, child, parent, child_name, parent_name in checks:
            orphans = set(child[column].dropna()) - set(parent[column].dropna())
            if orphans:
                warnings.warn(
                    f"{len(orphans)} {column}(s) in {child_name} not found in {parent_name}.txt",
                    UserWarning,
                    stacklevel=3,
                )

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


def _prefixed(values: pd.Series, prefix: str) -> pd.Series:
    """Prepend a prefix to identifiers, leaving missing values missing."""
    present = values.notna()
    labelled = values.astype(object)
    labelled[present] = prefix + "_" + values[present].astype(str)
    return labelled


def _with_prefix(feed: GTFSFeed, prefix: str) -> dict[str, pd.DataFrame]:
    """Return a feed's tables with every identifier prefixed and its feed recorded."""
    tables: dict[str, pd.DataFrame] = {}
    for name in _GTFS_TABLES:
        table = getattr(feed, name)
        if table.empty:
            continue
        table = table.copy(deep=False)
        for column in _ID_COLUMNS:
            if column in table.columns:
                table[column] = _prefixed(table[column], prefix)
        if name in _TABLES_RECORDING_FEED:
            table["feed"] = prefix
        tables[name] = table
    return tables


def _unique_prefix(prefix: str, used: set[str]) -> str:
    """Return a prefix no other feed has taken, numbering it if needed."""
    candidate, number = prefix, 1
    while candidate in used:
        number += 1
        candidate = f"{prefix}_{number}"
    return candidate


def merge_feeds(feeds: list[GTFSFeed], prefixes: list[str] | None = None) -> GTFSFeed:
    """Combine feeds into one, keeping IDs from different feeds distinct.

    Every feed's identifiers gain a prefix, so collisions cannot occur. Without
    ``prefixes``, each feed uses its ``onestop_id``, then its ``feed_key``, then
    ``feed_{position}``. These are stable across runs, whereas a feed's name may
    be absent, may be shared with another feed, and may change.

    Parameters
    ----------
    feeds : list of GTFSFeed
        Feeds to combine. A feed that is already merged keeps its prefixes.
    prefixes : list of str, optional
        One distinct prefix per feed, overriding the defaults.

    Returns
    -------
    GTFSFeed
        A new feed, or the input itself when given one already merged feed.

    Raises
    ------
    ValueError
        If there are no feeds, or if ``prefixes`` does not supply one distinct
        prefix per feed.
    """
    feeds = list(feeds)
    if not feeds:
        raise ValueError("merge_feeds needs at least one feed")
    if prefixes is not None:
        if len(prefixes) != len(feeds):
            raise ValueError(f"merge_feeds needs one prefix per feed, got {len(prefixes)}")
        if len(set(prefixes)) != len(prefixes):
            raise ValueError("merge_feeds needs distinct prefixes")
    if len(feeds) == 1 and feeds[0].sources:
        return feeds[0]

    used = {source["prefix"] for feed in feeds for source in feed.sources}
    parts: list[dict[str, pd.DataFrame]] = []
    sources: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for position, feed in enumerate(feeds):
        missing.extend(feed.missing)
        if feed.sources:
            parts.append({name: getattr(feed, name) for name in _GTFS_TABLES})
            sources.extend(feed.sources)
            continue
        default = feed.onestop_id or feed.feed_key or f"feed_{position}"
        prefix = _unique_prefix(prefixes[position] if prefixes else str(default), used)
        used.add(prefix)
        parts.append(_with_prefix(feed, prefix))
        sources.append(
            {
                "prefix": prefix,
                "onestop_id": feed.onestop_id,
                "feed_key": feed.feed_key,
                "name": feed.name,
            }
        )

    combined: dict[str, pd.DataFrame] = {}
    for name in _GTFS_TABLES:
        tables = [part[name] for part in parts if name in part and not part[name].empty]
        if tables:
            combined[name] = pd.concat(tables, ignore_index=True)
    return GTFSFeed(**combined, sources=sources, missing=missing)


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
        return load_zip(path, name=path.stem)
    if path.is_dir():
        return _load_from_dir(path)
    raise ValueError(f"GTFS path must be a .zip file or directory: {path}")


def load_zip(source: Any, name: str | None = None) -> GTFSFeed:
    """Load GTFS tables from a zip archive, given as a path or an open binary file.

    Tables may sit in a folder inside the archive.
    """
    with zipfile.ZipFile(source, "r") as archive:
        members: dict[str, zipfile.ZipInfo] = {}
        for info in archive.infolist():
            member = PurePosixPath(info.filename)
            if member.suffix == ".txt" and "__MACOSX" not in member.parts:
                members.setdefault(member.stem, info)

        tables: dict[str, pd.DataFrame] = {}
        for table in _GTFS_TABLES:
            info = members.get(table)
            if info is not None and info.file_size > 0:
                with archive.open(info) as handle:
                    tables[table] = _read_gtfs_csv(handle)
    return GTFSFeed(**tables, name=name)


def _load_from_dir(path: Path) -> GTFSFeed:
    """Load GTFS tables from a directory."""
    tables: dict[str, pd.DataFrame] = {}
    for table in _GTFS_TABLES:
        file_path = path / f"{table}.txt"
        if file_path.exists() and file_path.stat().st_size > 0:
            tables[table] = _read_gtfs_csv(file_path)
    return GTFSFeed(**tables, name=path.name)


def _read_gtfs_csv(path_or_buffer: Any) -> pd.DataFrame:
    """Read a GTFS CSV file as text, using pyarrow when it is available."""
    read_kwargs: dict[str, Any] = {
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
    table = pd.read_csv(path_or_buffer, **read_kwargs)
    table.columns = table.columns.str.strip()
    return table
