"""Exceptions for the data layer."""


class DataLayerError(Exception):
    """Base exception for data layer errors."""


class SourceError(DataLayerError):
    """Error related to data sources."""


class ExtractionError(SourceError):
    """Error during data extraction."""


class ValidationError(SourceError):
    """Error during source validation."""


class FileNotFoundError(SourceError):
    """Source file not found."""


class UnsupportedFormatError(SourceError):
    """Unsupported file format."""
