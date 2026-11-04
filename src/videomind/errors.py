"""Public error messages must never contain user-supplied values or raw SDK errors."""


class VideoMindError(Exception):
    """A safe, user-facing failure."""


class ConfigurationError(VideoMindError):
    """Invalid local configuration."""


class CredentialsError(VideoMindError):
    """Missing user-owned credentials; there is no fallback account."""


class MediaError(VideoMindError):
    """Invalid media or a failed local processing tool."""


class ProviderError(VideoMindError):
    """A sanitized remote service or capability failure."""


class BudgetError(VideoMindError):
    """Paid execution was not authorized or exceeds the conservative bound."""


class SourceError(VideoMindError):
    """Sanitized platform acquisition failure."""
