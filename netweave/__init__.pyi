"""Netweave: GTFS transit and OSM pedestrian network integration."""

__all__: list[str]
__version__: str

# Config
from .config import Settings as Settings
from .config import settings as settings

# Exceptions
from .exceptions import CalendarSelectionError as CalendarSelectionError
from .exceptions import EmptyNetworkError as EmptyNetworkError
from .exceptions import InvalidGTFS as InvalidGTFS
from .exceptions import MissingGTFSFile as MissingGTFSFile
from .exceptions import NetworkIntegrationError as NetworkIntegrationError
from .exceptions import NoFeedsFoundError as NoFeedsFoundError
from .exceptions import TimeFormatError as TimeFormatError
from .exceptions import TransitlandAPIError as TransitlandAPIError
from .exceptions import NetweaveError as NetweaveError
from .exceptions import UrbanAccessError as UrbanAccessError

# Types
from .types import IntegratedNetwork as IntegratedNetwork
from .types import OSMNetwork as OSMNetwork
from .types import TransitNetwork as TransitNetwork

# Pipeline
from .integration.core import integrate as integrate
from .io.gtfs import GTFSFeed as GTFSFeed
from .io.gtfs import load_feed as load_feed
from .io.gtfs import merge_feeds as merge_feeds
from .io.transitland import fetch_feeds as fetch_feeds
from .io.transitland import search_feeds as search_feeds
from .transform.gtfs import create_transit_network as create_transit_network

# Submodules (lazily loaded)
from . import integration as integration
from . import io as io
from . import osm as osm
from . import plot as plot
from . import transform as transform
