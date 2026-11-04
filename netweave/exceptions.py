"""Custom exceptions for netweave."""


class NetweaveError(Exception):
    """Base exception for all netweave errors."""


# Backward-compatibility alias
UrbanAccessError = NetweaveError


class InvalidGTFS(NetweaveError):  # noqa: N818
    """Raised when a GTFS feed fails validation."""


class NetworkIntegrationError(NetweaveError):
    """Raised when network integration fails."""


class EmptyNetworkError(NetweaveError):
    """Raised when a network has zero edges or nodes."""


class MissingGTFSFile(NetweaveError):  # noqa: N818
    """Raised when a required GTFS file is missing."""


class TimeFormatError(NetweaveError):
    """Raised when a time string does not match the expected HH:MM:SS format."""


class CalendarSelectionError(NetweaveError):
    """Raised when calendar selection produces no active service IDs."""


class TransitlandAPIError(NetweaveError):
    """Raised when a Transitland API request fails or returns an error."""


class NoFeedsFoundError(NetweaveError):
    """Raised when a Transitland search returns no matching GTFS feeds."""
