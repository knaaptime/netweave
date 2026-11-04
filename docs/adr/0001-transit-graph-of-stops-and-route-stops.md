# The transit graph is stops and route-stops, with wait on boarding

A transit network has a node for each stop and a node for each route-stop: one route, in one direction where the feed records direction, at one stop. Ride edges join consecutive route-stops and carry in-vehicle time. A boarding edge leads from a stop to a route-stop and carries half the mean headway. An alighting edge leads back at no cost. Connectors join stops to the pedestrian network and carry walk time. We chose this because each edge then has one kind of cost, and changing routes at a stop costs the wait for the next route and no walking.

The graph has one edge per connection, priced at the mean across trips in the time window. pandarm's graph has no clock, so a rider cannot board any particular trip, and parallel trip-level edges would only make every path take the fastest trip on record. Costs that truly differ belong in separate impedances on the same edge, not in separate edges.

## Considered Options

- **Connectors straight to route-stops, carrying walk plus wait**, as `urbanaccess` does. Changing routes at one stop then charges a walk to the nearest street node and back: 2.5 minutes at 100 m and 10 minutes at 400 m, for a rider who never leaves the stop.
- **Stops as the only transit nodes.** This gives a smaller graph, but a rider stays at the stop node when changing routes and pays nothing.
- **Wait on every ride edge**, as the code first attempted. A ten-stop ride then pays ten waits.
- **One edge per trip.** In five real feeds this produced 8 to 41 rows for each connection, while fewer than 1% of connections in the 7 to 10 AM window had trip times more than two minutes apart.

## Consequences

The graph holds one time window. Wait varies far more across the day than ride time does, so comparing periods means building a network for each, or later adding one impedance per named window on a shared graph.

Stops and route-stops are real nodes in the finished network, so points must not snap to them. A point on a route-stop would make walkers pay the wait to reach it, and let trips begun there skip the wait.
