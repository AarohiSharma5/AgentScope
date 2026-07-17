"""Single source of truth for the service and HTTP API versions.

``__version__`` is the deployable build version of the service; ``API_VERSION``
is the *contract* version exposed under ``/api/v1`` and advertised in the
``X-API-Version`` response header. They intentionally evolve independently: a
patch release of the service must not imply a new API contract.
"""

__version__ = "1.0.0"

# The current, canonical HTTP API version. Requests may use the versioned prefix
# (``/api/v1/...``) or the unversioned alias (``/api/...``), which always maps to
# the current version for backward compatibility with existing clients.
API_VERSION = "v1"

# Every API version this build still serves (newest first). Add entries here as
# older contracts are kept alive alongside newer ones.
SUPPORTED_API_VERSIONS = ("v1",)

__all__ = ["__version__", "API_VERSION", "SUPPORTED_API_VERSIONS"]
