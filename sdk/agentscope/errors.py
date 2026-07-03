"""Exception types raised by the AgentScope SDK."""


class AgentScopeError(Exception):
    """Base class for every error raised by the SDK."""


class ConfigurationError(AgentScopeError):
    """Raised when the SDK is misconfigured (e.g. an unknown option)."""


class ExporterError(AgentScopeError):
    """Raised when a span/trace cannot be exported to a backend."""
