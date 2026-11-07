.. _api_ref:

.. currentmodule:: netweave

API reference
=============

The pipeline is four calls, available at the top level of the package: find and
download GTFS feeds, build a transit network from them, and join it to a
pedestrian network built by pandarm. The result is a ``pandarm.Network`` whose
single impedance, ``minutes``, covers walking, waiting and riding.

Feeds
-----

Find and download GTFS feeds through Transitland, or read feeds you already
have. Feeds are merged by default, with every feed's identifiers prefixed so
that IDs from different agencies cannot collide.

.. autosummary::
   :toctree: generated/

   search_feeds
   fetch_feeds
   load_feed
   merge_feeds
   GTFSFeed

.. currentmodule:: netweave.io

.. autosummary::
   :toctree: generated/

   download_feed

Transit network
---------------

.. currentmodule:: netweave

A transit network has a node for each stop and for each route-stop: one route, in
one direction where the feed records direction, at one stop. Ride edges carry
in-vehicle time, boarding edges carry half the mean headway, and alighting edges
cost nothing.

.. autosummary::
   :toctree: generated/

   create_transit_network
   TransitNetwork

Integration
-----------

Join a transit network to a pedestrian network. Each stop connects to its nearest
pedestrian node, and the result keeps the pedestrian network's CRS and node IDs.

.. autosummary::
   :toctree: generated/

   integrate

Building blocks
---------------

.. currentmodule:: netweave.transform

The steps ``create_transit_network`` runs, exposed for inspecting a feed or
assembling a network differently.

.. autosummary::
   :toctree: generated/

   select_service
   timed_stop_times
   expand_frequencies
   compute_headways
   timetoseconds

Impedance
---------

Every cost in a network is expressed in minutes.

.. autosummary::
   :toctree: generated/

   walk_minutes
   ride_minutes
   wait_minutes
   to_minutes

Configuration
-------------

.. currentmodule:: netweave

``netweave.settings`` is the instance of :class:`Settings` the package uses.

.. autosummary::
   :toctree: generated/

   Settings

Exceptions
----------

Every error netweave raises derives from :class:`NetweaveError`.

.. autosummary::
   :toctree: generated/

   NetweaveError
   InvalidGTFS
   TimeFormatError
   CalendarSelectionError
   EmptyNetworkError
   NetworkIntegrationError
   TransitlandAPIError
   NoFeedsFoundError
