"""The storage port. Persistence is reachable only through the protocols in
``sobres.data.storage.base``; ``adapters/`` is the only place a database
driver is imported."""

from sobres.data.storage.base import (
    DateRange,
    FetchRecord,
    Observation,
    ObservationQuery,
    ObservationStore,
    SeriesKey,
    Storage,
    open_storage,
    registered_backends,
)

__all__ = [
    "DateRange",
    "FetchRecord",
    "Observation",
    "ObservationQuery",
    "ObservationStore",
    "SeriesKey",
    "Storage",
    "open_storage",
    "registered_backends",
]
