"""Exceptions for the data layer."""


class DataLayerError(Exception):
    """Base exception for data layer errors."""

    pass


class SourceError(DataLayerError):
    """Error related to data sources."""

    pass


class ExtractionError(SourceError):
    """Error during data extraction."""

    pass


class ValidationError(SourceError):
    """Error during source validation."""

    pass


class FileNotFoundError(SourceError):
    """Source file not found."""

    pass


class UnsupportedFormatError(SourceError):
    """Unsupported file format."""

    pass
