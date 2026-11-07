"""GTFS tables for tests, written the way a real feed writes them."""


def schedule(trips, **extra_tables):
    """Write GTFS tables from {trip: (route, direction, [(stop, time), ...])}.

    A time may be a pair of (arrival, departure), or None where a feed leaves it blank.
    """
    stop_ids = list(dict.fromkeys(row[0] for _, _, rows in trips.values() for row in rows))
    with_direction = any(direction is not None for _, direction, _ in trips.values())
    stop_rows = []
    for trip_id, (_, _, rows) in trips.items():
        for sequence, (stop_id, time) in enumerate(rows, start=1):
            arrival, departure = time if isinstance(time, tuple) else (time, time)
            stop_rows.append((trip_id, stop_id, str(sequence), arrival or "", departure or ""))
    tables = {
        "agency": {"agency_id": ["A"], "agency_name": ["Agency"]},
        "routes": {
            "route_id": list(dict.fromkeys(route for route, _, _ in trips.values())),
        },
        "trips": {
            "route_id": [route for route, _, _ in trips.values()],
            "trip_id": list(trips),
            "service_id": ["WK"] * len(trips),
        },
        "stops": {
            "stop_id": stop_ids,
            "stop_lat": [f"{37 + i * 0.001:.3f}" for i in range(len(stop_ids))],
            "stop_lon": [f"{-122 - i * 0.001:.3f}" for i in range(len(stop_ids))],
        },
        "stop_times": dict(
            zip(
                ("trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"),
                (list(column) for column in zip(*stop_rows, strict=True)),
                strict=True,
            )
        ),
        "calendar": {
            "service_id": ["WK"],
            **{
                day: ["1"]
                for day in (
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                )
            },
            "start_date": ["20260105"],
            "end_date": ["20260628"],
        },
    }
    tables["routes"]["agency_id"] = ["A"] * len(tables["routes"]["route_id"])
    tables["routes"]["route_type"] = ["3"] * len(tables["routes"]["route_id"])
    if with_direction:
        tables["trips"]["direction_id"] = [
            "" if direction is None else direction for _, direction, _ in trips.values()
        ]
    tables.update(extra_tables)
    return tables
