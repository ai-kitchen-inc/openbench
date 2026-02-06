"""Custom exceptions for data stores."""

from typing import Optional


class StoreError(Exception):
    """Base exception for all store errors."""

    pass


class IndexNotFoundError(StoreError):
    """Raised when a store index does not exist."""

    def __init__(self, index_name: str, message: Optional[str] = None):
        self.index_name = index_name
        self.message = message or f"Index '{index_name}' not found"
        super().__init__(self.message)


class StoreConnectionError(StoreError):
    """Raised when connection to the store fails."""

    def __init__(self, store_type: str, message: Optional[str] = None):
        self.store_type = store_type
        self.message = message or f"Failed to connect to {store_type} store"
        super().__init__(self.message)


class DimensionMismatchError(StoreError):
    """Raised when vector dimension does not match index configuration."""

    def __init__(self, expected: int, got: int, message: Optional[str] = None):
        self.expected = expected
        self.got = got
        self.message = message or f"Dimension mismatch: expected {expected}, got {got}"
        super().__init__(self.message)


class QuotaExceededError(StoreError):
    """Raised when API rate limit or quota is exceeded."""

    def __init__(self, retry_after: Optional[int] = None, message: Optional[str] = None):
        self.retry_after = retry_after
        self.message = message or "Rate limit exceeded"
        if retry_after:
            self.message += f". Retry after {retry_after} seconds"
        super().__init__(self.message)


class EmbeddingError(StoreError):
    """Raised when embedding generation fails."""

    def __init__(self, text_length: Optional[int] = None, message: Optional[str] = None):
        self.text_length = text_length
        self.message = message or "Failed to generate embedding"
        if text_length:
            self.message += f" for text of length {text_length}"
        super().__init__(self.message)


class ItemNotFoundError(StoreError):
    """Raised when a specific item is not found in the store."""

    def __init__(self, item_id: str, message: Optional[str] = None):
        self.item_id = item_id
        self.message = message or f"Item '{item_id}' not found"
        super().__init__(self.message)


class InvalidQueryError(StoreError):
    """Raised when a query is invalid or malformed."""

    def __init__(self, reason: Optional[str] = None, message: Optional[str] = None):
        self.reason = reason
        self.message = message or "Invalid query"
        if reason:
            self.message += f": {reason}"
        super().__init__(self.message)
