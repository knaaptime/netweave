# netweave

`netweave` is a package for weaving together GTFS-based transit networks and OSM-based pedestrian networks into an integrated routable multi-modal graph. It is a ground-up rewrite of the [`urbanaccess`]() package focused on

1. the modern scipy stack
2. vectorized computation wherever possible
3. 