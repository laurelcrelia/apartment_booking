"""Errors raised by the services; the message is shown to the user."""


class BookingError(Exception):
    """Raised for any invalid operation."""


class NotFoundError(BookingError):
    pass


class ConflictError(BookingError):
    """The request is valid but clashes with the current state of the data."""


class OverlapError(ConflictError):
    pass


class ServiceUnavailableError(BookingError):
    """Another service needed for the request could not be reached."""
