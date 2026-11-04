"""Tests for choosing which service a transit network represents."""

import pytest

from netweave.exceptions import CalendarSelectionError
from netweave.io.gtfs import load_feed
from netweave.transform.gtfs import create_transit_network

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WEEKDAYS = DAYS[:5]
AM = ("07:00:00", "10:00:00")


def on_service(tables, service_id, start="20260105", end="20260628", days=WEEKDAYS):
    """Put every trip in the tables on one service with the given validity."""
    tables["trips"]["service_id"] = [service_id] * len(tables["trips"]["trip_id"])
    tables["calendar"] = {
        "service_id": [service_id],
        **{day: ["1" if day in days else "0"] for day in DAYS},
        "start_date": [start],
        "end_date": [end],
    }
    return tables


def combined(*parts):
    """Append several sets of GTFS tables into one feed."""
    result = {}
    for part in parts:
        for table, columns in part.items():
            target = result.setdefault(table, {column: [] for column in columns})
            for column, values in columns.items():
                target.setdefault(column, []).extend(values)
    return result


def service_date(network, position=0):
    return network.metadata["feeds"][position]["service_date"]


def routes_served(network):
    return {route.rsplit("_", 1)[1] for route in network.edges["route_id"].dropna()}


class TestChoosingADay:
    def test_day_or_date_is_required(self, line_tables, write_feed) -> None:
        feed = load_feed(write_feed(line_tables()))
        with pytest.raises(ValueError, match="exactly one"):
            create_transit_network(feed, timerange=AM)

    def test_day_and_date_together_are_refused(self, line_tables, write_feed) -> None:
        feed = load_feed(write_feed(line_tables()))
        with pytest.raises(ValueError, match="exactly one"):
            create_transit_network(feed, day="monday", date="20260105", timerange=AM)

    def test_unknown_day_is_refused(self, line_tables, write_feed) -> None:
        feed = load_feed(write_feed(line_tables()))
        with pytest.raises(ValueError, match="funday"):
            create_transit_network(feed, day="funday", timerange=AM)

    def test_malformed_date_is_refused(self, line_tables, write_feed) -> None:
        feed = load_feed(write_feed(line_tables()))
        with pytest.raises(ValueError, match="YYYYMMDD"):
            create_transit_network(feed, date="2026-01-05", timerange=AM)


class TestDay:
    def test_seasons_are_not_combined(self, line_tables, write_feed) -> None:
        winter = on_service(line_tables(route_id="10"), "WINTER", "20260105", "20260531")
        summer = on_service(
            line_tables(
                route_id="20", first_trip=100, first_stop=2000, departures=("08:00:00", "08:10:00")
            ),
            "SUMMER",
            "20260601",
            "20260830",
        )
        network = create_transit_network(
            load_feed(write_feed(combined(winter, summer))), day="monday", timerange=AM
        )
        assert routes_served(network) == {"10"}
        assert service_date(network) == "20260105"

    def test_busiest_such_weekday_wins(self, line_tables, write_feed) -> None:
        small = on_service(
            line_tables(route_id="10", departures=("08:00:00",)), "WINTER", "20260105", "20260531"
        )
        large = on_service(
            line_tables(route_id="20", first_trip=100, first_stop=2000),
            "SUMMER",
            "20260601",
            "20260830",
        )
        network = create_transit_network(
            load_feed(write_feed(combined(small, large))), day="monday", timerange=AM
        )
        assert routes_served(network) == {"20"}
        assert service_date(network) == "20260601"

    def test_ties_go_to_the_earliest_date(self, line_tables, write_feed) -> None:
        network = create_transit_network(
            load_feed(write_feed(line_tables())), day="monday", timerange=AM
        )
        assert service_date(network) == "20260105"

    def test_a_holiday_is_not_chosen(self, line_tables, write_feed) -> None:
        tables = line_tables()
        tables["calendar_dates"] = {
            "service_id": ["WK"],
            "date": ["20260105"],
            "exception_type": ["2"],
        }
        network = create_transit_network(load_feed(write_feed(tables)), day="monday", timerange=AM)
        assert service_date(network) == "20260112"

    def test_feed_with_only_calendar_dates(self, line_tables, write_feed) -> None:
        tables = line_tables()
        del tables["calendar"]
        tables["calendar_dates"] = {
            "service_id": ["WK", "WK"],
            "date": ["20260110", "20260112"],
            "exception_type": ["1", "1"],
        }
        network = create_transit_network(load_feed(write_feed(tables)), day="monday", timerange=AM)
        assert service_date(network) == "20260112"

    def test_each_feed_chooses_its_own_date(self, line_tables, write_feed) -> None:
        first = on_service(line_tables(route_id="10"), "A", "20260105", "20260301")
        second = on_service(line_tables(route_id="20"), "B", "20260601", "20260830")
        feeds = [
            load_feed(write_feed(first, name="first")),
            load_feed(write_feed(second, name="second")),
        ]
        network = create_transit_network(feeds, day="monday", timerange=AM)
        assert routes_served(network) == {"10", "20"}
        assert service_date(network, 0) == "20260105"
        assert service_date(network, 1) == "20260601"

    def test_weekday_no_feed_runs_on_raises(self, line_tables, write_feed) -> None:
        with pytest.raises(CalendarSelectionError, match="saturday"):
            create_transit_network(
                load_feed(write_feed(line_tables())), day="saturday", timerange=AM
            )

    def test_feed_without_that_weekday_warns(self, line_tables, write_feed) -> None:
        weekdays = load_feed(write_feed(line_tables(route_id="10"), name="weekdays"))
        weekend = load_feed(
            write_feed(
                on_service(line_tables(route_id="20"), "SAT", days=("saturday",)), name="weekend"
            )
        )
        weekdays.onestop_id, weekend.onestop_id = "f-wk", "f-sat"
        with pytest.warns(UserWarning, match="f-sat"):
            network = create_transit_network([weekdays, weekend], day="monday", timerange=AM)
        assert routes_served(network) == {"10"}
        assert service_date(network, 1) is None


class TestDate:
    def test_calendar_applies_without_a_day(self, line_tables, write_feed) -> None:
        network = create_transit_network(
            load_feed(write_feed(line_tables())), date="20260302", timerange=AM
        )
        assert routes_served(network) == {"10"}
        assert service_date(network) == "20260302"

    def test_removed_service_is_removed_and_added_service_added(
        self, line_tables, write_feed
    ) -> None:
        regular = line_tables(route_id="10")
        holiday = on_service(
            line_tables(route_id="20", first_trip=100, first_stop=2000), "HOL", days=()
        )
        tables = combined(regular, holiday)
        tables["calendar_dates"] = {
            "service_id": ["WK", "HOL"],
            "date": ["20260302", "20260302"],
            "exception_type": ["2", "1"],
        }
        network = create_transit_network(
            load_feed(write_feed(tables)), date="20260302", timerange=AM
        )
        assert routes_served(network) == {"20"}

    def test_date_outside_the_feed_raises(self, line_tables, write_feed) -> None:
        with pytest.raises(CalendarSelectionError, match="20300101"):
            create_transit_network(
                load_feed(write_feed(line_tables())), date="20300101", timerange=AM
            )

    def test_feed_without_service_on_the_date_warns(self, line_tables, write_feed) -> None:
        running = load_feed(write_feed(line_tables(route_id="10"), name="running"))
        ended = load_feed(
            write_feed(
                on_service(line_tables(route_id="20"), "OLD", "20200101", "20200601"), name="ended"
            )
        )
        running.onestop_id, ended.onestop_id = "f-run", "f-old"
        with pytest.warns(UserWarning, match="f-old"):
            network = create_transit_network([running, ended], date="20260302", timerange=AM)
        assert routes_served(network) == {"10"}
        assert service_date(network, 0) == "20260302"
        assert service_date(network, 1) is None


class TestMultipleFeeds:
    def test_a_list_of_feeds_is_merged(self, line_tables, write_feed) -> None:
        first = load_feed(write_feed(line_tables(route_id="10"), name="first"))
        second = load_feed(write_feed(line_tables(route_id="20"), name="second"))
        first.onestop_id, second.onestop_id = "f-a", "f-b"
        network = create_transit_network([first, second], day="monday", timerange=AM)
        assert {record["prefix"] for record in network.metadata["feeds"]} == {"f-a", "f-b"}

    def test_missing_feeds_reach_the_metadata(self, line_tables, write_feed) -> None:
        feed = load_feed(write_feed(line_tables()))
        feed.missing = [{"feed": "f-x", "name": None, "reason": "licence"}]
        network = create_transit_network(feed, day="monday", timerange=AM)
        assert network.metadata["missing_feeds"] == feed.missing
