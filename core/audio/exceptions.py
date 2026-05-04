"""Audio engine exception hierarchy."""


class AudioEngineError(Exception):
    """Base class for all audio engine errors."""


class ChannelError(AudioEngineError):
    """Raised when a channel id is invalid or in an unexpected state."""


class FormatError(AudioEngineError):
    """Raised when a file's format cannot be decoded by BASS."""
