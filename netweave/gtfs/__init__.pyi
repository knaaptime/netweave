"""GTFS subpackage for netweave."""

__all__: list[str]

from .feed import GTFSFeed as GTFSFeed
from .feed import load_feed as load_feed
from .calendar import highest_frequency_date as highest_frequency_date
from .calendar import select_service_ids as select_service_ids
from .schedule import add_unique_ids as add_unique_ids
from .schedule import interpolate_stop_times as interpolate_stop_times
from .schedule import seconds_to_time as seconds_to_time
from .schedule import select_by_time_range as select_by_time_range
from .schedule import timetoseconds as timetoseconds
from .network import create_transit_network as create_transit_network
from .network import _assign_shape_to_edges as _assign_shape_to_edges
from .network import _build_shape_geometries as _build_shape_geometries
from .network import _build_stop_geometries as _build_stop_geometries
from .headways import compute_headways as compute_headways
from ._sources import FeedRegistry as FeedRegistry
from ._sources import download_feed as download_feed
from ._sources import unzip_feed as unzip_feed
from .transitland import download_feed as transitland_download_feed
from .transitland import fetch_feeds as fetch_feeds
from .transitland import search_feeds as search_feeds
from .transitland import transit_network_from_transitland as transit_network_from_transitland
