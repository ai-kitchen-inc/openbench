"""Local DINOv3 CIFAR-10 image similarity MCP service."""

from app.config import AppConfig
from app.service import ImageSearchService, get_service

__all__ = ["AppConfig", "ImageSearchService", "get_service"]
