"""Dynamic adapter credential persistence backends."""

from .interface import AdapterSecretStore
from .memory import MemorySecretStore
from .namespace import NamespacedSecretStore

__all__ = [
    "AdapterSecretStore",
    "MemorySecretStore",
    "NamespacedSecretStore",
]
