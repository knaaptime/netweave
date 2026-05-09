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

# Submodules (lazily loaded)
from . import gtfs as gtfs
from . import network as network
from . import osm as osm
from . import plot as plot
