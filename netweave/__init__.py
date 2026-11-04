"""Netweave: GTFS transit and OSM pedestrian network integration."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("netweave")
except PackageNotFoundError:
    __version__ = "unknown"

import lazy_loader as lazy

__getattr__, __dir__, __all__ = lazy.attach_stub(__name__, __file__)
