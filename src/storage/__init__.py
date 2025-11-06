"""
Storage abstraction layer.
Provides a clean interface for data persistence that can be swapped out.
"""
from .interface import StorageInterface
from .sqlite_storage import SQLiteStorage

__all__ = ['StorageInterface', 'SQLiteStorage']










