"""Storage adapters — the ONLY place a database driver is imported.

Importing this package registers every adapter with the backend registry.
``schema`` and ``migrations`` live here too: they are expressed through
SQLAlchemy Core, the dialect layer that stays below the port.
"""

from sobres.data.storage.adapters import sqlite as _sqlite  # noqa: F401
