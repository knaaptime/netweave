"""Netweave: GTFS transit and OSM pedestrian network integration."""


try:
    from netweave._version import version as __version__
except ImportError:
    __version__ = "unknown"

import lazy_loader as lazy

__getattr__, __dir__, __all__ = lazy.attach_stub(__name__, __file__)
