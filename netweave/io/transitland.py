"""Transitland v2 REST API client for discovering and downloading GTFS feeds."""

import os
import time
import warnings
import zipfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import requests
from tqdm import tqdm

from netweave._logging import _log, status
from netweave.config import settings
from netweave.exceptions import InvalidGTFS, NoFeedsFoundError, TransitlandAPIError
from netweave.io.gtfs import GTFSFeed, load_zip, merge_feeds

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TRANSITLAND_BASE_URL: str = settings.gtfs_api.get(
    "transitland", "https://transit.land/api/v2/rest"
)
_DEFAULT_LIMIT: int = 100
_MAX_RETRIES: int = 3
_RETRY_BACKOFF: float = 1.0
_STOPS_PER_PAGE: int = 100
_MAX_STOP_PAGES: int = 50

# Errors that mean one feed is unusable, not that the whole request has failed.
_FEED_ERRORS: tuple[type[Exception], ...] = (
    TransitlandAPIError,
    InvalidGTFS,
    zipfile.BadZipFile,
    ValueError,
    OSError,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_api_key(api_key: str | None = None) -> str:
    """Resolve the Transitland API key.

    Parameters
    ----------
    api_key : str, optional
        Explicit API key. If provided, it takes precedence.

    Returns
    -------
    str
        The resolved API key.

    Raises
    ------
    TransitlandAPIError
        If no API key is available.
    """
    if api_key is not None:
        return api_key
    env_key = os.environ.get("TRANSITLAND_API_KEY")
    if env_key:
        return env_key
    raise TransitlandAPIError(
        "Transitland API key is required. Pass it as `api_key` or set the "
        "TRANSITLAND_API_KEY environment variable."
    )


def _without_key(error: Exception | str, api_key: str) -> str:
    """Return an error message with the API key removed, since URLs carry it."""
    return str(error).replace(api_key, "***")


def _request(
    url: str,
    params: dict[str, Any],
    api_key: str,
    timeout: int = 60,
) -> dict[str, Any]:
    """Make a GET request to the Transitland API with retries.

    Parameters
    ----------
    url : str
        Request URL.
    params : dict
        Query parameters.
    api_key : str
        API key for the request.
    timeout : int, optional
        Request timeout in seconds.

    Returns
    -------
    dict
        Parsed JSON response.

    Raises
    ------
    TransitlandAPIError
        If the request fails after all retries.
    """
    request_params = {**params, "apikey": api_key}
    last_error = "no response"

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=request_params, timeout=timeout)
            if response.status_code == 429:
                last_error = "rate limit reached (HTTP 429)"
                wait = _RETRY_BACKOFF * (2 ** (attempt - 1))
                _log(
                    f"Transitland rate limit hit (429). Retrying in {wait:.1f}s "
                    f"(attempt {attempt}/{_MAX_RETRIES})...",
                    level=30,
                )
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            last_error = _without_key(exc, api_key)
            if attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF * (2 ** (attempt - 1))
                _log(
                    f"Transitland request failed: {last_error}. Retrying in {wait:.1f}s "
                    f"(attempt {attempt}/{_MAX_RETRIES})...",
                    level=30,
                )
                time.sleep(wait)

    raise TransitlandAPIError(
        f"Transitland API request failed after {_MAX_RETRIES} attempts: {last_error}"
    )


def _search_feeds_page(
    params: dict[str, Any],
    api_key: str,
) -> tuple[list[dict[str, Any]], int | None]:
    """Fetch a single page of feed search results.

    Parameters
    ----------
    params : dict
        Query parameters for the feeds endpoint.
    api_key : str
        API key.

    Returns
    -------
    tuple
        (list of feed dicts, next_page cursor or None)
    """
    url = f"{_TRANSITLAND_BASE_URL}/feeds"
    data = _request(url, params, api_key)
    feeds = data.get("feeds", [])
    meta = data.get("meta", {})
    after = meta.get("after")
    return feeds, after


def _bbox_to_string(bbox: tuple[float, float, float, float]) -> str:
    """Convert a bbox tuple to a Transitland bbox string.

    Transitland expects ``min_lon,min_lat,max_lon,max_lat``.

    Parameters
    ----------
    bbox : tuple[float, float, float, float]
        Bounding box as ``(min_lon, min_lat, max_lon, max_lat)``.

    Returns
    -------
    str
        Comma-separated bbox string.
    """
    if not (isinstance(bbox, (tuple, list)) and len(bbox) == 4):
        raise ValueError(
            "bbox must be a tuple/list of 4 elements "
            f"(min_lon, min_lat, max_lon, max_lat), got: {bbox}"
        )
    min_lon, min_lat, max_lon, max_lat = bbox
    return f"{min_lon},{min_lat},{max_lon},{max_lat}"


def _parse_feeds(feeds: list[dict[str, Any]]) -> pd.DataFrame:
    """Parse a list of feed dicts into a DataFrame.

    Parameters
    ----------
    feeds : list[dict]
        Raw feed objects from the API.

    Returns
    -------
    pd.DataFrame
        Feed metadata with one row per feed.
    """
    if not feeds:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for feed in feeds:
        row: dict[str, Any] = {
            "feed_key": feed.get("id"),
            "onestop_id": feed.get("onestop_id"),
            "name": feed.get("name"),
            "spec": feed.get("spec"),
        }
        urls = feed.get("urls", {})
        row["static_current"] = urls.get("static_current")
        row["static_historic"] = urls.get("static_historic", [])
        row["realtime_vehicle_positions"] = urls.get("realtime_vehicle_positions")
        row["realtime_trip_updates"] = urls.get("realtime_trip_updates")
        row["realtime_alerts"] = urls.get("realtime_alerts")

        license_info = feed.get("license", {})
        row["license_spdx"] = license_info.get("spdx_identifier")
        row["license_url"] = license_info.get("url")
        row["license_redistribution"] = license_info.get("redistribution_allowed")
        row["license_commercial"] = license_info.get("commercial_use_allowed")
        row["license_create_derived"] = license_info.get("create_derived_product")

        feed_state = feed.get("feed_state", {})
        row["feed_state"] = feed_state

        rows.append(row)

    return pd.DataFrame(rows)


def _download_zip_to_memory(
    feed_key: str,
    api_key: str,
    timeout: int = 300,
    disable_tqdm: bool = False,
) -> BytesIO:
    """Download the latest GTFS zip for a feed into memory.

    Parameters
    ----------
    feed_key : str
        Feed ID or Onestop ID.
    api_key : str
        API key.
    timeout : int, optional
        Download timeout in seconds.
    disable_tqdm : bool, optional
        If True, suppress the per-download progress bar. Useful when
        downloads are managed by an outer progress indicator.

    Returns
    -------
    BytesIO
        In-memory zip file.

    Raises
    ------
    TransitlandAPIError
        If the download fails.
    """
    url = f"{_TRANSITLAND_BASE_URL}/feeds/{feed_key}/download_latest_feed_version"
    params = {"apikey": api_key}

    _log(f"Downloading GTFS for feed '{feed_key}' from Transitland...")
    try:
        response = requests.get(url, params=params, stream=True, timeout=timeout)
        response.raise_for_status()
        buffer = _stream_to_memory(response, f"{feed_key}.zip", disable_tqdm)
    except requests.exceptions.RequestException as exc:
        raise TransitlandAPIError(
            f"Failed to download feed '{feed_key}': {_without_key(exc, api_key)}"
        ) from None

    if not zipfile.is_zipfile(buffer):
        raise TransitlandAPIError(f"Transitland did not return a zip file for feed '{feed_key}'")
    buffer.seek(0)
    _log(f"Download complete for feed '{feed_key}'")
    return buffer


def _stream_to_memory(response: requests.Response, label: str, disable_tqdm: bool) -> BytesIO:
    """Read a streamed response into memory, showing progress unless disabled."""
    buffer = BytesIO()
    total = int(response.headers.get("content-length", 0))
    with tqdm(
        desc=label,
        total=total,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        disable=disable_tqdm,
    ) as pbar:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                buffer.write(chunk)
                pbar.update(len(chunk))
    buffer.seek(0)
    return buffer


def _download_from_source(
    feed_key: str,
    source_url: str,
    refusal: TransitlandAPIError,
    timeout: int,
    disable_tqdm: bool,
) -> BytesIO:
    """Download a feed from the address its publisher serves it at.

    The API key belongs to Transitland, so it is not sent to this host.

    Parameters
    ----------
    feed_key : str
        Feed ID or Onestop ID, used to label progress.
    source_url : str
        The publisher's address for the feed.
    refusal : TransitlandAPIError
        Why Transitland did not supply the feed.
    timeout : int
        Download timeout in seconds.
    disable_tqdm : bool
        If True, suppress the progress bar.

    Returns
    -------
    BytesIO
        The downloaded file.

    Raises
    ------
    TransitlandAPIError
        If the download fails, giving both reasons.
    """
    _log(f"{refusal}. Trying the source URL of feed '{feed_key}'.")
    try:
        response = requests.get(source_url, stream=True, timeout=timeout)
        response.raise_for_status()
        return _stream_to_memory(response, f"{feed_key}.zip", disable_tqdm)
    except requests.exceptions.RequestException as exc:
        raise TransitlandAPIError(f"{refusal}. Its source URL also failed: {exc}") from None


def _get_feed_ids_from_stops(
    bbox_str: str,
    api_key: str,
    max_pages: int = _MAX_STOP_PAGES,
) -> set[str]:
    """Query the Transitland /stops endpoint to find feeds with actual stops in bbox.

    The /feeds endpoint with ``bbox`` returns feeds whose *registered* bounding
    box overlaps the query, which includes feeds with incorrect or overly broad
    service areas (e.g., a Sydney feed appearing for a Charleston, SC query).
    The /stops endpoint returns only stops whose coordinates fall within the
    bbox, so collecting the unique ``feed_onestop_id`` values gives a reliable
    list of feeds that actually serve the area.

    Parameters
    ----------
    bbox_str : str
        Comma-separated bbox string ``min_lon,min_lat,max_lon,max_lat``.
    api_key : str
        Transitland API key.
    max_pages : int, optional
        Maximum number of paginated requests. Reaching it raises a warning,
        because a feed whose stops lie beyond the limit would go unnoticed.

    Returns
    -------
    set[str]
        Set of feed onestop_ids that have at least one stop in the bbox.
    """
    url = f"{_TRANSITLAND_BASE_URL}/stops"
    params: dict[str, Any] = {"bbox": bbox_str, "limit": _STOPS_PER_PAGE}
    feed_ids: set[str] = set()
    after: int | None = None

    for _ in range(max_pages):
        page_params = {**params}
        if after is not None:
            page_params["after"] = after

        data = _request(url, page_params, api_key)
        stops = data.get("stops", [])
        if not stops:
            return feed_ids

        for stop in stops:
            feed_id = stop.get("feed_version", {}).get("feed", {}).get("onestop_id")
            if feed_id:
                feed_ids.add(feed_id)

        after = data.get("meta", {}).get("after")
        if after is None:
            return feed_ids

    warnings.warn(
        f"Stopped checking stops after {max_pages * _STOPS_PER_PAGE:,}, so the feed list may "
        "be incomplete for an area this large. Pass verify_stops=False to list every feed "
        "whose registered area overlaps it.",
        UserWarning,
        stacklevel=3,
    )
    return feed_ids


def _polygon_bbox(polygon: Any) -> tuple[float, float, float, float]:
    """Return a boundary's bounds in longitude and latitude."""
    if isinstance(polygon, (gpd.GeoDataFrame, gpd.GeoSeries)):
        if polygon.crs is not None:
            polygon = polygon.to_crs(4326)
        min_lon, min_lat, max_lon, max_lat = polygon.total_bounds
    else:
        min_lon, min_lat, max_lon, max_lat = polygon.bounds
    return float(min_lon), float(min_lat), float(max_lon), float(max_lat)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_feeds(
    bbox: tuple[float, float, float, float] | None = None,
    polygon: Any | None = None,
    search: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    api_key: str | None = None,
    verify_stops: bool = True,
) -> pd.DataFrame:
    """Search for GTFS feeds on Transitland.

    At least one of ``bbox``, ``polygon``, or ``search`` must be provided.

    When ``bbox`` or ``polygon`` is provided, the search first queries the
    Transitland ``/stops`` endpoint to find feeds that have *actual stops*
    within the bounding box. This avoids returning feeds whose registered
    bounding boxes are incorrect or overly broad (e.g., a national operator
    whose bbox happens to overlap a local query area but has no service
    there). Set ``verify_stops=False`` to skip this verification and use
    the faster but less accurate ``/feeds`` endpoint directly.

    Parameters
    ----------
    bbox : tuple[float, float, float, float], optional
        Bounding box as ``(min_lon, min_lat, max_lon, max_lat)``.
    polygon : geopandas.GeoDataFrame or shapely.geometry.Polygon, optional
        Geographic boundary. Its bounds, in longitude and latitude, become the
        bounding box for the API query.
    search : str, optional
        Free-text search query (e.g., ``"caltrain"``).
    limit : int, optional
        Maximum number of feeds to return (default 100).
    api_key : str, optional
        Transitland API key. Falls back to the ``TRANSITLAND_API_KEY``
        environment variable.
    verify_stops : bool, optional
        If True (default), verify that feeds have actual stops within the
        bounding box by querying the ``/stops`` endpoint. This is more
        accurate but adds an extra API call. Set to False for faster
        results when accuracy is less critical.

    Returns
    -------
    pd.DataFrame
        Feed metadata with columns: ``feed_key``, ``onestop_id``, ``name``,
        ``spec``, ``static_current``, ``static_historic``,
        ``license_redistribution``, etc.

    Raises
    ------
    TransitlandAPIError
        If the API request fails or the API key is missing.
    NoFeedsFoundError
        If no feeds match the query.
    ValueError
        If no spatial or text filter is provided.
    """
    if bbox is None and polygon is None and search is None:
        raise ValueError("At least one of `bbox`, `polygon`, or `search` must be provided.")

    key = _get_api_key(api_key)
    params: dict[str, Any] = {"spec": "gtfs", "limit": min(limit, 100)}

    if search is not None:
        params["search"] = search

    bbox_str: str | None = None
    if bbox is not None:
        bbox_str = _bbox_to_string(bbox)
        params["bbox"] = bbox_str

    if polygon is not None:
        bbox_str = _bbox_to_string(_polygon_bbox(polygon))
        params["bbox"] = bbox_str

    # For bbox/polygon queries, verify feeds by checking actual stops
    verified_feed_ids: set[str] | None = None
    if bbox_str is not None and verify_stops:
        verified_feed_ids = _get_feed_ids_from_stops(bbox_str, key)
        if not verified_feed_ids:
            raise NoFeedsFoundError("No GTFS feeds found with stops in the specified area.")

    all_feeds: list[dict[str, Any]] = []
    after: int | None = None
    page = 0

    while len(all_feeds) < limit:
        page_params = {**params}
        if after is not None:
            page_params["after"] = after

        feeds, after = _search_feeds_page(page_params, key)
        if not feeds:
            break

        # Filter to verified feeds if we did stop-based verification
        if verified_feed_ids is not None:
            feeds = [f for f in feeds if f.get("onestop_id") in verified_feed_ids]

        all_feeds.extend(feeds)
        page += 1

        if after is None:
            break

    if not all_feeds:
        raise NoFeedsFoundError("No GTFS feeds found matching the query.")

    df = _parse_feeds(all_feeds[:limit])

    status(f"Found {len(df)} feed(s) on Transitland")
    return df


def download_feed(
    feed_key: str,
    api_key: str | None = None,
    output_dir: str | Path | None = None,
    timeout: int = 300,
    disable_tqdm: bool = False,
    source_url: str | None = None,
) -> GTFSFeed | tuple[GTFSFeed, Path]:
    """Download the latest GTFS feed version from Transitland.

    Transitland serves a feed only if its license allows redistribution. Given a
    ``source_url``, a feed Transitland does not supply comes from there instead.

    Parameters
    ----------
    feed_key : str
        Feed ID or Onestop ID.
    api_key : str, optional
        Transitland API key. Falls back to ``TRANSITLAND_API_KEY``.
    output_dir : str or pathlib.Path, optional
        Directory to save the raw zip file. If provided, the zip is saved
        and a ``(GTFSFeed, Path)`` tuple is returned.
    timeout : int, optional
        Download timeout in seconds.
    disable_tqdm : bool, optional
        If True, suppress the download progress bar.
    source_url : str, optional
        The address the feed's publisher serves it at, as listed in the
        ``static_current`` column of :func:`netweave.search_feeds`. The API key
        is not sent to it.

    Returns
    -------
    GTFSFeed or tuple[GTFSFeed, Path]
        The loaded feed, optionally paired with the path to the saved zip.

    Raises
    ------
    TransitlandAPIError
        If the download fails.
    """
    key = _get_api_key(api_key)
    try:
        buffer = _download_zip_to_memory(feed_key, key, timeout=timeout, disable_tqdm=disable_tqdm)
    except TransitlandAPIError as refusal:
        if source_url is None:
            raise
        buffer = _download_from_source(feed_key, source_url, refusal, timeout, disable_tqdm)

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        zip_path = output_dir / f"{feed_key}.zip"
        with open(zip_path, "wb") as f:
            f.write(buffer.getvalue())
        return load_zip(buffer, name=feed_key), zip_path

    return load_zip(buffer, name=feed_key)


def _value(record: dict[str, Any], key: str) -> str | None:
    """Return a field of a search result as text, or None if it is empty."""
    value = record.get(key)
    return None if value is None or pd.isna(value) else str(value)


def fetch_feeds(
    bbox: tuple[float, float, float, float] | None = None,
    polygon: Any | None = None,
    search: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    api_key: str | None = None,
    merge: bool = True,
    output_dir: str | Path | None = None,
    timeout: int = 300,
    max_workers: int = 4,
) -> GTFSFeed | list[GTFSFeed]:
    """Search Transitland and download all matching GTFS feeds.

    Every matching feed is collected, whatever its license says about
    redistribution, because netweave only downloads and analyzes feeds. Transitland
    does not serve a feed whose license forbids redistribution, so a feed it does not
    supply comes from the source URL it lists.

    One unusable feed does not stop the others. Each feed that fails raises a
    warning naming it and the reason, and a merged feed records them in
    ``missing``, because a study that loses an agency without notice would simply
    be wrong.

    Parameters
    ----------
    bbox : tuple[float, float, float, float], optional
        Bounding box as ``(min_lon, min_lat, max_lon, max_lat)``.
    polygon : geopandas.GeoDataFrame or shapely.geometry.Polygon, optional
        Geographic boundary.
    search : str, optional
        Free-text search query.
    limit : int, optional
        Maximum number of feeds to return (default 100).
    api_key : str, optional
        Transitland API key.
    merge : bool, optional
        If True (default), merge all downloaded feeds into a single
        :class:`GTFSFeed`. If False, return a list of individual feeds.
    output_dir : str or pathlib.Path, optional
        Directory to save raw zip files.
    timeout : int, optional
        Download timeout in seconds.
    max_workers : int, optional
        Maximum number of parallel download threads (default 4).
        Set to 1 for sequential downloads.

    Returns
    -------
    GTFSFeed or list[GTFSFeed]
        Merged feed or list of feeds, in the order of the search results.

    Raises
    ------
    TransitlandAPIError
        If the search request fails.
    NoFeedsFoundError
        If no feeds match the query, or none of them could be used.
    """
    table = search_feeds(
        bbox=bbox,
        polygon=polygon,
        search=search,
        limit=limit,
        api_key=api_key,
    )

    targets: list[tuple[str, dict[str, Any]]] = []
    for record in table.to_dict("records"):
        feed_id = _value(record, "onestop_id") or _value(record, "feed_key")
        if feed_id is not None:
            targets.append((feed_id, record))

    def _download_one(target: tuple[str, dict[str, Any]]) -> GTFSFeed | str:
        feed_id, record = target
        try:
            result = download_feed(
                feed_id,
                api_key=api_key,
                output_dir=output_dir,
                timeout=timeout,
                disable_tqdm=True,
                source_url=_value(record, "static_current"),
            )
            feed = result[0] if isinstance(result, tuple) else result
            feed.validate()
        except _FEED_ERRORS as error:
            return str(error)
        feed.name = _value(record, "name")
        feed.onestop_id = _value(record, "onestop_id")
        feed.feed_key = _value(record, "feed_key")
        return feed

    feeds: list[GTFSFeed] = []
    missing: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        outcomes = executor.map(_download_one, targets)
        for (feed_id, record), outcome in tqdm(
            zip(targets, outcomes, strict=True),
            total=len(targets),
            desc="Downloading feeds",
            unit="feed",
        ):
            if isinstance(outcome, GTFSFeed):
                feeds.append(outcome)
            else:
                missing.append({"feed": feed_id, "name": _value(record, "name"), "reason": outcome})

    for record in missing:
        warnings.warn(
            f"Feed '{record['feed']}' was left out: {record['reason']}",
            UserWarning,
            stacklevel=2,
        )

    if not feeds:
        reasons = "; ".join(f"{record['feed']}: {record['reason']}" for record in missing)
        raise NoFeedsFoundError(f"No feeds could be used. {reasons}")

    if merge:
        merged = merge_feeds(feeds)
        merged.missing = missing
        tqdm.write(f"Merged {len(feeds)} feed(s) into a single GTFSFeed")
        return merged

    tqdm.write(f"Downloaded {len(feeds)} feed(s)")
    return feeds
