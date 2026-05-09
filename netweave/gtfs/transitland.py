"""Transitland v2 REST API client for discovering and downloading GTFS feeds."""


import os
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from tqdm import tqdm

from netweave._logging import _log, status
from netweave.config import settings
from netweave.exceptions import NoFeedsFoundError, TransitlandAPIError
from netweave.gtfs.feed import GTFSFeed, load_feed
from netweave.gtfs.network import create_transit_network
from netweave.types import TransitNetwork

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TRANSITLAND_BASE_URL: str = settings.gtfs_api.get(
    "transitland", "https://transit.land/api/v2/rest"
)
_DEFAULT_LIMIT: int = 100
_MAX_RETRIES: int = 3
_RETRY_BACKOFF: float = 1.0


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
    last_exception: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=request_params, timeout=timeout)
            if response.status_code == 429:
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
            last_exception = exc
            if attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF * (2 ** (attempt - 1))
                _log(
                    f"Transitland request failed: {exc}. Retrying in {wait:.1f}s "
                    f"(attempt {attempt}/{_MAX_RETRIES})...",
                    level=30,
                )
                time.sleep(wait)

    raise TransitlandAPIError(
        f"Transitland API request failed after {_MAX_RETRIES} attempts: {last_exception}"
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
            f"bbox must be a tuple/list of 4 elements (min_lon, min_lat, max_lon, max_lat), got: {bbox}"
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
    except requests.exceptions.RequestException as exc:
        raise TransitlandAPIError(
            f"Failed to download feed '{feed_key}': {exc}"
        ) from exc

    buffer = BytesIO()
    total = int(response.headers.get("content-length", 0))
    with tqdm(
        desc=f"{feed_key}.zip",
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
    _log(f"Download complete for feed '{feed_key}'")
    return buffer


def _load_feed_from_buffer(buffer: BytesIO) -> GTFSFeed:
    """Load a GTFSFeed from an in-memory zip buffer.

    Parameters
    ----------
    buffer : BytesIO
        In-memory zip file.

    Returns
    -------
    GTFSFeed
    """
    with zipfile.ZipFile(buffer, "r") as zf:
        # Extract to a temporary directory
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            zf.extractall(tmpdir)
            return load_feed(tmpdir)


def _get_feed_ids_from_stops(
    bbox_str: str,
    api_key: str,
    max_pages: int = 50,
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
        Maximum number of paginated requests (default 50).

    Returns
    -------
    set[str]
        Set of feed onestop_ids that have at least one stop in the bbox.
    """
    url = f"{_TRANSITLAND_BASE_URL}/stops"
    params: dict[str, Any] = {
        "bbox": bbox_str,
        "limit": 100,
    }
    feed_ids: set[str] = set()
    after: int | None = None

    for _ in range(max_pages):
        page_params = {**params}
        if after is not None:
            page_params["after"] = after

        data = _request(url, page_params, api_key)
        stops = data.get("stops", [])
        if not stops:
            break

        for stop in stops:
            feed_id = (
                stop.get("feed_version", {})
                .get("feed", {})
                .get("onestop_id")
            )
            if feed_id:
                feed_ids.add(feed_id)

        after = data.get("meta", {}).get("after")
        if after is None:
            break

    return feed_ids


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
        Geographic boundary. Total bounds are computed and converted to a
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
        raise ValueError(
            "At least one of `bbox`, `polygon`, or `search` must be provided."
        )

    key = _get_api_key(api_key)
    params: dict[str, Any] = {"spec": "gtfs", "limit": min(limit, 100)}

    if search is not None:
        params["search"] = search

    bbox_str: str | None = None
    if bbox is not None:
        bbox_str = _bbox_to_string(bbox)
        params["bbox"] = bbox_str

    if polygon is not None:
        # Handle GeoDataFrame or shapely Polygon
        try:
            import geopandas as gpd

            if isinstance(polygon, gpd.GeoDataFrame):
                # total_bounds: [minx, miny, maxx, maxy]
                total_bounds = polygon.total_bounds
                # Convert to tuple (min_lon, min_lat, max_lon, max_lat)
                bbox_tuple = (float(total_bounds[0]), float(total_bounds[1]), float(total_bounds[2]), float(total_bounds[3]))
            else:
                # Assume shapely Polygon
                minx, miny, maxx, maxy = polygon.bounds
                bbox_tuple = (float(minx), float(miny), float(maxx), float(maxy))
            bbox_str = _bbox_to_string(bbox_tuple)
            params["bbox"] = bbox_str
        except ImportError:
            # Fallback: try shapely directly
            try:
                from shapely.geometry import Polygon

                if isinstance(polygon, Polygon):
                    minx, miny, maxx, maxy = polygon.bounds
                    bbox_tuple = (float(minx), float(miny), float(maxx), float(maxy))
                    bbox_str = _bbox_to_string(bbox_tuple)
                    params["bbox"] = bbox_str
                else:
                    raise TypeError(
                        "polygon must be a GeoDataFrame or shapely Polygon"
                    )
            except ImportError as exc:
                raise ImportError(
                    "geopandas or shapely is required for polygon input"
                ) from exc

    # For bbox/polygon queries, verify feeds by checking actual stops
    verified_feed_ids: set[str] | None = None
    if bbox_str is not None and verify_stops:
        verified_feed_ids = _get_feed_ids_from_stops(bbox_str, key)
        if not verified_feed_ids:
            raise NoFeedsFoundError(
                "No GTFS feeds found with stops in the specified area."
            )

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
            feeds = [
                f for f in feeds
                if f.get("onestop_id") in verified_feed_ids
            ]

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
) -> GTFSFeed | tuple[GTFSFeed, Path]:
    """Download the latest GTFS feed version from Transitland.

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
    buffer = _download_zip_to_memory(feed_key, key, timeout=timeout, disable_tqdm=disable_tqdm)

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        zip_path = output_dir / f"{feed_key}.zip"
        with open(zip_path, "wb") as f:
            f.write(buffer.getvalue())
        feed = _load_feed_from_buffer(buffer)
        return feed, zip_path

    return _load_feed_from_buffer(buffer)


def fetch_feeds(
    bbox: tuple[float, float, float, float] | None = None,
    polygon: Any | None = None,
    search: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    api_key: str | None = None,
    merge: bool = True,
    skip_no_redistribution: bool = True,
    output_dir: str | Path | None = None,
    timeout: int = 300,
    max_workers: int = 4,
) -> GTFSFeed | list[GTFSFeed]:
    """Search Transitland and download all matching GTFS feeds.

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
    skip_no_redistribution : bool, optional
        If True (default), skip feeds that do not allow redistribution.
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
        Merged feed or list of feeds.

    Raises
    ------
    TransitlandAPIError
        If the API request or download fails.
    NoFeedsFoundError
        If no feeds match the query.
    """
    df = search_feeds(
        bbox=bbox,
        polygon=polygon,
        search=search,
        limit=limit,
        api_key=api_key,
    )

    from concurrent.futures import ThreadPoolExecutor, as_completed

    feeds: list[GTFSFeed] = []
    feed_keys: list[str] = []

    for _, row in df.iterrows():
        feed_key = row.get("onestop_id") or row.get("feed_key")
        if pd.isna(feed_key):
            continue

        redistribution = row.get("license_redistribution")
        if skip_no_redistribution and redistribution == "no":
            _log(
                f"Skipping feed '{feed_key}' — redistribution not allowed by license",
                level=30,
            )
            continue
        feed_keys.append(str(feed_key))

    if not feed_keys:
        raise NoFeedsFoundError(
            "No feeds could be downloaded. All matching feeds were skipped or failed."
        )

    def _download_one(feed_key: str) -> GTFSFeed | None:
        try:
            result = download_feed(
                feed_key,
                api_key=api_key,
                output_dir=output_dir,
                timeout=timeout,
                disable_tqdm=True,
            )
            return result[0] if isinstance(result, tuple) else result
        except TransitlandAPIError as exc:
            _log(f"Failed to download feed '{feed_key}': {exc}", level=40)
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_download_one, fk): fk for fk in feed_keys}
        with tqdm(
            total=len(feed_keys),
            desc="Downloading feeds",
            unit="feed",
        ) as pbar:
            for future in as_completed(futures):
                feed = future.result()
                if feed is not None:
                    feeds.append(feed)
                pbar.update(1)
                pbar.set_postfix_str(f"{len(feeds)}/{len(feed_keys)} ok")

    if not feeds:
        raise NoFeedsFoundError(
            "No feeds could be downloaded. All matching feeds were skipped or failed."
        )

    if merge:
        merged = feeds[0]
        for i, feed in enumerate(feeds[1:], start=1):
            merged = merged.merge(feed, prefix=f"f{i}")
        tqdm.write(f"Merged {len(feeds)} feed(s) into a single GTFSFeed")
        return merged

    tqdm.write(f"Downloaded {len(feeds)} feed(s)")
    return feeds


def transit_network_from_transitland(
    bbox: tuple[float, float, float, float] | None = None,
    polygon: Any | None = None,
    search: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    api_key: str | None = None,
    output_dir: str | Path | None = None,
    timeout: int = 300,
    **network_kwargs: Any,
) -> TransitNetwork:
    """Search Transitland, download feeds, and create a transit network.

    This is a high-level convenience that combines :func:`fetch_feeds` with
    :func:`create_transit_network`.

    Parameters
    ----------
    bbox : tuple[float, float, float, float], optional
        Bounding box as ``(min_lon, min_lat, max_lon, max_lat)``.
    polygon : geopandas.GeoDataFrame or shapely.geometry.Polygon, optional
        Geographic boundary.
    search : str, optional
        Free-text search query.
    limit : int, optional
        Maximum number of feeds to return.
    api_key : str, optional
        Transitland API key.
    output_dir : str or pathlib.Path, optional
        Directory to save raw zip files.
    timeout : int, optional
        Download timeout in seconds.
    **network_kwargs
        Additional arguments forwarded to :func:`create_transit_network`
        (e.g., ``day``, ``timerange``, ``date``, ``simplify``).

    Returns
    -------
    TransitNetwork
        Transit network ready for integration with a pedestrian network.

    Raises
    ------
    TransitlandAPIError
        If the API request or download fails.
    NoFeedsFoundError
        If no feeds match the query.
    """
    feed = fetch_feeds(
        bbox=bbox,
        polygon=polygon,
        search=search,
        limit=limit,
        api_key=api_key,
        merge=True,
        output_dir=output_dir,
        timeout=timeout,
    )
    # fetch_feeds with merge=True returns a single GTFSFeed
    if isinstance(feed, list):
        feed = feed[0]
    return create_transit_network(feed, **network_kwargs)
