# netweave

netweave turns GTFS feeds and a pedestrian network into one integrated network whose costs are all travel time, ready for analysis in pandarm.

## Language

### Inputs

**Feed**:
A GTFS dataset as published by a transit provider, covering one or more agencies.
_Avoid_: GTFS (as a noun for the data), dataset

**Pedestrian network**:
The graph of walkable paths that riders use to reach and leave transit, whatever its source.
_Avoid_: OSM network, walk network

### Networks

**Transit network**:
The graph of stops, route-stops and the edges among them that a set of feeds yields for a chosen day and time window.
_Avoid_: GTFS network

**Time window**:
The span of a service day, on the GTFS clock, that a transit network represents. Times past 24:00:00 fall on the following calendar morning.
_Avoid_: timerange, period

**Integrated network**:
A pedestrian network and a transit network joined by connectors, with every edge priced in time. It is a pandarm network.
_Avoid_: multimodal graph, combined network

### Graph

**Stop**:
A place where riders board or alight, as listed in a feed, treated as its own node.

**Stranded stop**:
A stop too far from any pedestrian node to have connectors. Trips still pass through it, but riders cannot reach it on foot.

**Route-stop**:
One route, in one direction where the feed records direction, at one stop, treated as its own node. A stop served by three one-way routes is three route-stops.
_Avoid_: stop node, transit node

**Edge**:
A connection from one node to another. Two nodes share at most one edge in each direction, so differences in cost are impedances on that edge and never parallel edges.
_Avoid_: link, segment

**Ride edge**:
An edge between consecutive route-stops of a route, priced by in-vehicle time.
_Avoid_: transit edge, hop

**Walk edge**:
An edge of the pedestrian network, priced by walking time.
_Avoid_: OSM edge

**Boarding edge**:
An edge from a stop to one of its route-stops, priced by wait time.

**Alighting edge**:
An edge from a route-stop to its stop, carrying no cost.

**Connector**:
An edge between a stop and a pedestrian node, in either direction, priced by walk time.
_Avoid_: osm to transit, transit to osm

### Cost

**Impedance**:
A named cost on an edge, measured in minutes. One edge can carry several.
_Avoid_: weight, distance

**Headway**:
The time between consecutive departures of a route at a stop.
_Avoid_: frequency

**Wait time**:
The time a rider expects to spend at a stop before boarding.
_Avoid_: headway impedance, wait penalty
